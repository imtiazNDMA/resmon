"""Server-side PMD Monitor client foundation.

This module owns PMD Monitor authentication, upstream caching, stale fallback, and
basic data cleaning. It deliberately does not define public API routes yet; Phase 8C
routes should depend on this seam and keep network behavior out of repositories.
"""

from __future__ import annotations

import json
import math
import ssl
import threading
import time
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import requests
from core.config import get_settings
from requests.adapters import HTTPAdapter

SENTINEL_VALUES = {-9999.0, -999.0, 999.0, 9999.0}
INT32_SENTINEL_MIN_ABS = 2_000_000.0


class PmdConfigError(RuntimeError):
    """PMD Monitor is not configured for live upstream calls."""


class PmdUpstreamError(RuntimeError):
    """PMD Monitor upstream request failed."""


@dataclass(frozen=True)
class PmdCacheEntry:
    value: Any
    expires_at: float
    stored_at: float


@dataclass(frozen=True)
class PmdCacheResult:
    value: Any
    cache_status: str  # fresh | fetched | stale


@dataclass(frozen=True)
class PmdSource:
    key: str
    source_name: str
    upstream_path: str
    ttl_seconds: int
    geometry_type: str
    limitations: str


@dataclass(frozen=True)
class PmdForecastElement:
    key: str
    data_type: str
    element: str
    label: str
    unit: str
    accumulation: str
    status: str
    notes: str
    color_ramp: str
    max_frames: int


PMD_SOURCES: dict[str, PmdSource] = {
    "monitor_stations": PmdSource(
        key="monitor_stations",
        source_name="PMD Monitor",
        upstream_path="api/gts_warnning_data",
        ttl_seconds=300,
        geometry_type="Point",
        limitations="Live station observations; station coverage and sensor availability vary.",
    ),
    "monitor_warnings": PmdSource(
        key="monitor_warnings",
        source_name="PMD Monitor",
        upstream_path="api/get_warning_id + api/warning_area",
        ttl_seconds=120,
        geometry_type="Polygon/MultiPolygon",
        limitations="Active warning polygons only; empty response can mean no active warnings.",
    ),
    "monitor_monsoon": PmdSource(
        key="monitor_monsoon",
        source_name="PMD Monitor",
        upstream_path="api/monsoon_warnning_data",
        ttl_seconds=300,
        geometry_type="Point/Polygon",
        limitations="Monsoon-season warnings; schema may include text-only rows without geometry.",
    ),
    "monitor_glof_observations": PmdSource(
        key="monitor_glof_observations",
        source_name="PMD Monitor GLOF",
        upstream_path="api/glofStationObsData",
        ttl_seconds=120,
        geometry_type="Point",
        limitations=(
            "GLOF station telemetry requires sentinel-value filtering and connectivity checks."
        ),
    ),
    "monitor_lightning": PmdSource(
        key="monitor_lightning",
        source_name="PMD Monitor Lightning",
        upstream_path="api/radar/thunder/lightHis",
        ttl_seconds=180,
        geometry_type="Point",
        limitations="Recent strike window only; zero strikes is a normal no-data condition.",
    ),
    "monitor_city_forecast": PmdSource(
        key="monitor_city_forecast",
        source_name="PMD Monitor City Forecast",
        upstream_path="api/getBandRCityForecast12",
        ttl_seconds=1800,
        geometry_type="Point",
        limitations=(
            "City forecast features include nested forecast arrays from upstream JSON strings."
        ),
    ),
    "nwfc_observations": PmdSource(
        key="nwfc_observations",
        source_name="PMD NWFC",
        upstream_path="api/pmd/nwfc/observations/",
        ttl_seconds=300,
        geometry_type="Point",
        limitations="NWFC scrape; useful as a station-observation cross-check.",
    ),
    "ffd_waterlevels": PmdSource(
        key="ffd_waterlevels",
        source_name="FFD Flood Forecasting Division",
        upstream_path="get-ffd-waterlevels/",
        ttl_seconds=300,
        geometry_type="Point",
        limitations="Current river-gauge snapshot; history must be sampled/persisted separately.",
    ),
}

PMD_FORECAST_ELEMENTS: dict[str, PmdForecastElement] = {
    "pmd_pred_hourtpe": PmdForecastElement(
        key="pmd_pred_hourtpe",
        data_type="WRFPRS",
        element="HOURTPE",
        label="Hourly precipitation",
        unit="mm",
        accumulation="1h",
        status="candidate",
        notes="Candidate only; requires live metadata and raster inspection before UI exposure.",
        color_ramp="project_precip_fallback",
        max_frames=24,
    ),
    "pmd_pred_sixtpe": PmdForecastElement(
        key="pmd_pred_sixtpe",
        data_type="WRFPRS",
        element="SIXTPE",
        label="6h precipitation",
        unit="mm",
        accumulation="6h",
        status="candidate",
        notes="Candidate only; accumulation reset semantics are not yet confirmed.",
        color_ramp="project_precip_fallback",
        max_frames=20,
    ),
    "pmd_pred_twelvetpe": PmdForecastElement(
        key="pmd_pred_twelvetpe",
        data_type="WRFPRS",
        element="TWELVETPE",
        label="12h precipitation",
        unit="mm",
        accumulation="12h",
        status="candidate",
        notes="Candidate only; time labels and accumulation window are not yet confirmed.",
        color_ramp="project_precip_fallback",
        max_frames=16,
    ),
    "pmd_pred_daytpe": PmdForecastElement(
        key="pmd_pred_daytpe",
        data_type="WRFPRS",
        element="DAYTPE",
        label="24h precipitation",
        unit="mm",
        accumulation="24h",
        status="candidate",
        notes="Candidate only; daily-total vs rolling-24h semantics are not yet confirmed.",
        color_ramp="project_precip_fallback",
        max_frames=14,
    ),
}

EXCLUDED_PMD_ENDPOINTS = frozenset(
    {
        "api/pmd/monitor/debug/",
        "api/pmd/nwfc/debug-station/",
        "raw_upstream_probe",
    }
)


class PmdLegacyTLSAdapter(HTTPAdapter):
    """Requests adapter for PMD Monitor's self-signed/legacy TLS host only."""

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
        except Exception:
            pass
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1
        except Exception:
            pass
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


def pmd_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.pmd_monitor_url and settings.pmd_monitor_user and settings.pmd_monitor_pass
    )


def pmd_source(key: str) -> PmdSource:
    return PMD_SOURCES[key]


def pmd_forecast_element(key: str) -> PmdForecastElement:
    return PMD_FORECAST_ELEMENTS[key]


def pmd_forecast_element_candidates() -> list[PmdForecastElement]:
    return list(PMD_FORECAST_ELEMENTS.values())


def summarize_model_time_response(payload: Any) -> dict[str, Any]:
    """Summarize PMD modelTimeList output without depending on one vendor shape."""
    cleaned = clean_pmd_value(payload)
    rows: list[Any]
    if isinstance(cleaned, list):
        rows = cleaned
    elif isinstance(cleaned, dict):
        rows = []
        for key in ("data", "items", "rows", "results", "model_times", "times"):
            value = cleaned.get(key)
            if isinstance(value, list):
                rows = value
                break
        if not rows:
            rows = [cleaned]
    else:
        rows = []

    times: list[str] = []
    frames = 0
    for row in rows:
        if isinstance(row, str):
            text = row.strip()
            if text:
                times.append(text)
            continue
        if not isinstance(row, dict):
            continue
        for key in ("model_time", "modelTime", "run", "run_time", "date", "time"):
            text = _text(row.get(key))
            if text:
                times.append(text)
                break
        frame_list = _first(row, "frames", "steps", "forecast_times", "dates")
        if isinstance(frame_list, list):
            frames += len(frame_list)

    return {
        "available": bool(rows),
        "row_count": len(rows),
        "model_times": times,
        "frame_count": frames or None,
    }


def latest_model_time(payload: Any) -> str | None:
    summary = summarize_model_time_response(payload)
    times = summary["model_times"]
    if not times:
        return None
    return str(times[-1])


def normalize_prediction_frames(payload: Any) -> list[dict[str, Any]]:
    cleaned = clean_pmd_value(payload)
    rows: list[Any]
    if isinstance(cleaned, list):
        rows = cleaned
    elif isinstance(cleaned, dict):
        rows = []
        for key in ("steps", "frames", "data", "items", "rows", "results"):
            value = cleaned.get(key)
            if isinstance(value, list):
                rows = value
                break
    else:
        rows = []

    frames = []
    for index, row in enumerate(rows):
        if isinstance(row, str):
            frames.append({"date": row, "upstream_index": index})
            continue
        if not isinstance(row, dict):
            continue
        date = _text(
            _first(row, "date", "datetime", "forecast_time", "valid_time", "time", "step")
        )
        url = _text(_first(row, "url", "png", "image_url", "raster_url"))
        bounds = _parsed_optional_json(_first(row, "bounds", "bbox"))
        coordinates = _parsed_optional_json(_first(row, "coordinates", "corners"))
        frames.append(
            {
                "date": date or str(index),
                "upstream_index": index,
                "upstream_url": url,
                "bounds": bounds if isinstance(bounds, list) else None,
                "coordinates": coordinates if isinstance(coordinates, list) else None,
            }
        )
    return frames


def thin_prediction_frames(frames: list[dict[str, Any]], max_frames: int) -> list[dict[str, Any]]:
    if len(frames) <= max_frames:
        return frames
    early_count = min(8, max_frames)
    early = frames[:early_count]
    remaining_slots = max_frames - early_count
    if remaining_slots <= 0:
        return early
    tail = frames[early_count:]
    stride = max(1, math.ceil(len(tail) / remaining_slots))
    return early + tail[::stride][:remaining_slots]


def _number(value: Any) -> float | None:
    value = clean_pmd_value(value)
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    value = clean_pmd_value(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bool_or_none(value: Any) -> bool | None:
    value = clean_pmd_value(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "ok", "online", "active"}:
            return True
        if lowered in {"false", "0", "offline", "inactive"}:
            return False
    return None


def _first(props: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in props and props[key] is not None:
            return props[key]
    return None


def _station_items(payload: Any) -> list[tuple[dict[str, Any] | None, dict[str, Any]]]:
    payload = clean_pmd_value(payload)
    if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
        items = []
        for feature in payload.get("features") or []:
            if not isinstance(feature, dict):
                continue
            props = feature.get("properties") or {}
            if isinstance(props, dict):
                items.append((feature.get("geometry"), props))
        return items
    if isinstance(payload, dict):
        for key in ("features", "data", "items", "rows", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return _station_items(value)
    if isinstance(payload, list):
        items = []
        for row in payload:
            if isinstance(row, dict) and row.get("type") == "Feature":
                props = row.get("properties") or {}
                if isinstance(props, dict):
                    items.append((row.get("geometry"), props))
            elif isinstance(row, dict):
                items.append((None, row))
        return items
    return []


def _point_geometry(
    geometry: dict[str, Any] | None, props: dict[str, Any]
) -> dict[str, Any] | None:
    if isinstance(geometry, dict) and geometry.get("type") == "Point":
        coords = geometry.get("coordinates")
        if isinstance(coords, list | tuple) and len(coords) >= 2:
            lon = _number(coords[0])
            lat = _number(coords[1])
            if lon is not None and lat is not None:
                return {"type": "Point", "coordinates": [lon, lat]}
    lon = _number(_first(props, "lon", "lng", "long", "longitude", "x"))
    lat = _number(_first(props, "lat", "latitude", "y"))
    if lon is None or lat is None:
        return None
    return {"type": "Point", "coordinates": [lon, lat]}


def _geometry_from_props(
    geometry: dict[str, Any] | None, props: dict[str, Any]
) -> dict[str, Any] | None:
    if isinstance(geometry, dict) and geometry.get("type"):
        return geometry
    for key in ("geometry", "geom", "area", "polygon", "coordinates"):
        parsed = _parsed_optional_json(props.get(key))
        if isinstance(parsed, dict) and parsed.get("type"):
            return parsed
    return _point_geometry(geometry, props)


def normalize_monitor_station_features(
    payload: Any, *, cache_status: str, fetched_at: datetime | None = None
) -> dict[str, Any]:
    """Normalize PMD Monitor station observations to our public GeoJSON contract."""
    source = pmd_source("monitor_stations")
    timestamp = fetched_at or datetime.now(UTC)
    features = []
    for geometry, raw_props in _station_items(payload):
        props = clean_pmd_value(raw_props)
        if not isinstance(props, dict):
            continue
        point = _point_geometry(geometry, props)
        if point is None:
            continue
        date_time = _text(_first(props, "date_time", "datetime", "obs_time", "time"))
        features.append(
            {
                "type": "Feature",
                "geometry": point,
                "properties": {
                    "station_id": _text(_first(props, "station_id", "id")),
                    "code": _text(_first(props, "code", "station_code")),
                    "name": _text(_first(props, "name", "station_name")),
                    "station_type": _text(_first(props, "station_type", "type")),
                    "date_time": date_time,
                    "temperature_c": _number(_first(props, "temperature", "temp", "tem")),
                    "humidity_pct": _number(_first(props, "humidity", "rhu")),
                    "pressure_hpa": _number(_first(props, "pressure", "prs")),
                    "wind_speed_mps": _number(_first(props, "wind_speed", "wspd")),
                    "wind_direction_deg": _number(_first(props, "wind_direction", "wdir")),
                    "rain_1h_mm": _number(_first(props, "rain_1h", "rain1h")),
                    "rain_6h_mm": _number(_first(props, "rain_6h", "rain6h")),
                    "rain_24h_mm": _number(_first(props, "rain_24h", "rain24h", "pre24")),
                    "visibility_km": _number(_first(props, "visibility", "vis")),
                    "status": _bool_or_none(_first(props, "status", "online")),
                    "warn_temp": _text(_first(props, "warn_temp")),
                    "warn_wind": _text(_first(props, "warn_wind")),
                    "warn_rain": _text(_first(props, "warn_rain")),
                    "warn_vis": _text(_first(props, "warn_vis")),
                    "source": source.source_name,
                    "source_timestamp": date_time,
                    "fetched_at": timestamp,
                    "cache_status": cache_status,
                    "stale": cache_status == "stale",
                    "ttl_seconds": source.ttl_seconds,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def normalize_nwfc_observation_features(
    payload: Any, *, cache_status: str, fetched_at: datetime | None = None
) -> dict[str, Any]:
    """Normalize PMD NWFC station observations to our public GeoJSON contract."""
    source = pmd_source("nwfc_observations")
    timestamp = fetched_at or datetime.now(UTC)
    features = []
    for geometry, raw_props in _station_items(payload):
        props = clean_pmd_value(raw_props)
        if not isinstance(props, dict):
            continue
        point = _point_geometry(geometry, props)
        if point is None:
            continue
        date_time = _text(
            _first(props, "date_time", "datetime", "obs_time", "time", "valid_time")
        )
        weather_text = _text(_first(props, "weather", "weather_text", "description"))
        features.append(
            {
                "type": "Feature",
                "geometry": point,
                "properties": {
                    "station_id": _text(_first(props, "station_id", "id")),
                    "code": _text(_first(props, "code", "station_code")),
                    "name": _text(_first(props, "name", "station_name")),
                    "date_time": date_time,
                    "weather_text": weather_text,
                    "weather_icon": _text(_first(props, "weather_icon", "icon", "icon_url")),
                    "temperature_c": _number(_first(props, "temperature", "temp", "tem")),
                    "humidity_pct": _number(_first(props, "humidity", "rhu")),
                    "pressure_hpa": _number(_first(props, "pressure", "prs")),
                    "wind_speed_mps": _number(_first(props, "wind_speed", "wspd")),
                    "wind_direction_deg": _number(_first(props, "wind_direction", "wdir")),
                    "rain_24h_mm": _number(_first(props, "rain_24h", "rain24h", "pre24")),
                    "source": source.source_name,
                    "source_timestamp": date_time,
                    "fetched_at": timestamp,
                    "cache_status": cache_status,
                    "stale": cache_status == "stale",
                    "ttl_seconds": source.ttl_seconds,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def normalize_glof_observation_features(
    payload: Any, *, cache_status: str, fetched_at: datetime | None = None
) -> dict[str, Any]:
    """Normalize PMD GLOF station telemetry to our public GeoJSON contract."""
    source = pmd_source("monitor_glof_observations")
    timestamp = fetched_at or datetime.now(UTC)
    features = []
    for geometry, raw_props in _station_items(payload):
        props = clean_pmd_value(raw_props)
        if not isinstance(props, dict):
            continue
        point = _point_geometry(geometry, props)
        if point is None:
            continue
        date_time = _text(
            _first(props, "date_time", "datetime", "obs_time", "time", "last_update")
        )
        features.append(
            {
                "type": "Feature",
                "geometry": point,
                "properties": {
                    "station_id": _text(_first(props, "station_id", "id")),
                    "code": _text(_first(props, "code", "station_code")),
                    "name": _text(_first(props, "name", "station_name")),
                    "date_time": date_time,
                    "connected": _bool_or_none(
                        _first(props, "connected", "connectivity", "online", "status")
                    ),
                    "alert_level": _text(_first(props, "alert_level", "alert", "warning")),
                    "rainfall_mm": _number(_first(props, "rainfall", "rain", "precip", "pre")),
                    "flow_cms": _number(_first(props, "flow", "discharge", "flow_cms")),
                    "water_level_m": _number(_first(props, "water_level", "level", "wl")),
                    "temperature_c": _number(_first(props, "temperature", "temp", "tem")),
                    "source": source.source_name,
                    "source_timestamp": date_time,
                    "fetched_at": timestamp,
                    "cache_status": cache_status,
                    "stale": cache_status == "stale",
                    "ttl_seconds": source.ttl_seconds,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def normalize_lightning_features(
    payload: Any, *, hours: int, cache_status: str, fetched_at: datetime | None = None
) -> dict[str, Any]:
    """Normalize recent PMD lightning strikes to our public GeoJSON contract."""
    source = pmd_source("monitor_lightning")
    timestamp = fetched_at or datetime.now(UTC)
    features = []
    for geometry, raw_props in _station_items(payload):
        props = clean_pmd_value(raw_props)
        if not isinstance(props, dict):
            continue
        point = _point_geometry(geometry, props)
        if point is None:
            continue
        strike_time = _text(
            _first(props, "strike_time", "date_time", "datetime", "time", "timestamp")
        )
        features.append(
            {
                "type": "Feature",
                "geometry": point,
                "properties": {
                    "strike_id": _text(_first(props, "strike_id", "id")),
                    "strike_time": strike_time,
                    "polarity": _text(_first(props, "polarity", "type")),
                    "peak_current_ka": _number(
                        _first(props, "peak_current", "current", "peak_current_ka")
                    ),
                    "multiplicity": _number(_first(props, "multiplicity", "strokes")),
                    "window_hours": hours,
                    "source": source.source_name,
                    "source_timestamp": strike_time,
                    "fetched_at": timestamp,
                    "cache_status": cache_status,
                    "stale": cache_status == "stale",
                    "ttl_seconds": source.ttl_seconds,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _parsed_optional_json(value: Any) -> Any:
    value = clean_pmd_value(value)
    parsed = parse_json_string(value)
    return clean_pmd_value(parsed)


def normalize_ffd_waterlevel_features(
    payload: Any, *, cache_status: str, fetched_at: datetime | None = None
) -> dict[str, Any]:
    """Normalize FFD river gauge water-level snapshots to GeoJSON points."""
    source = pmd_source("ffd_waterlevels")
    timestamp = fetched_at or datetime.now(UTC)
    features = []
    for geometry, raw_props in _station_items(payload):
        props = clean_pmd_value(raw_props)
        if not isinstance(props, dict):
            continue
        point = _point_geometry(geometry, props)
        if point is None:
            continue
        date_time = _text(
            _first(props, "date_time", "datetime", "obs_time", "time", "last_update")
        )
        gauges = _parsed_optional_json(_first(props, "gauges", "gauge", "readings"))
        features.append(
            {
                "type": "Feature",
                "geometry": point,
                "properties": {
                    "station_id": _text(_first(props, "station_id", "id", "site_id")),
                    "code": _text(_first(props, "code", "station_code", "site_code")),
                    "name": _text(_first(props, "name", "station_name", "site_name")),
                    "river": _text(_first(props, "river", "river_name")),
                    "date_time": date_time,
                    "water_level_m": _number(_first(props, "water_level", "level", "wl")),
                    "discharge_cusecs": _number(
                        _first(props, "discharge_cusecs", "discharge", "flow_cusecs")
                    ),
                    "discharge_cumecs": _number(_first(props, "discharge_cumecs", "flow_cms")),
                    "status": _text(_first(props, "status", "flood_status", "category")),
                    "gauges": gauges if isinstance(gauges, list | dict) else None,
                    "source": source.source_name,
                    "source_timestamp": date_time,
                    "fetched_at": timestamp,
                    "cache_status": cache_status,
                    "stale": cache_status == "stale",
                    "ttl_seconds": source.ttl_seconds,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def normalize_warning_features(
    payload: Any, *, cache_status: str, fetched_at: datetime | None = None
) -> dict[str, Any]:
    """Normalize PMD active warnings to GeoJSON features."""
    source = pmd_source("monitor_warnings")
    timestamp = fetched_at or datetime.now(UTC)
    features = []
    for geometry, raw_props in _station_items(payload):
        props = clean_pmd_value(raw_props)
        if not isinstance(props, dict):
            continue
        feature_geometry = _geometry_from_props(geometry, props)
        if feature_geometry is None:
            continue
        forecast_time = _text(_first(props, "forecast_time", "valid_time", "valid_from"))
        data_time = _text(_first(props, "data_time", "date_time", "datetime", "issued_at"))
        features.append(
            {
                "type": "Feature",
                "geometry": feature_geometry,
                "properties": {
                    "warning_id": _text(_first(props, "warning_id", "id")),
                    "severity": _text(_first(props, "severity", "level", "warning_level")),
                    "hazard": _text(_first(props, "hazard", "element", "data_type")),
                    "model": _text(_first(props, "model", "source_model")),
                    "forecast_time": forecast_time,
                    "data_time": data_time,
                    "message": _text(_first(props, "message", "description", "text")),
                    "area_name": _text(_first(props, "area_name", "area", "district")),
                    "source": source.source_name,
                    "source_timestamp": data_time or forecast_time,
                    "fetched_at": timestamp,
                    "cache_status": cache_status,
                    "stale": cache_status == "stale",
                    "ttl_seconds": source.ttl_seconds,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def normalize_monsoon_features(
    payload: Any, *, cache_status: str, fetched_at: datetime | None = None
) -> dict[str, Any]:
    """Normalize PMD monsoon warning rows to GeoJSON where geometry is available."""
    source = pmd_source("monitor_monsoon")
    timestamp = fetched_at or datetime.now(UTC)
    features = []
    for geometry, raw_props in _station_items(payload):
        props = clean_pmd_value(raw_props)
        if not isinstance(props, dict):
            continue
        feature_geometry = _geometry_from_props(geometry, props)
        if feature_geometry is None:
            continue
        data_time = _text(_first(props, "data_time", "date_time", "datetime", "issued_at"))
        forecast = _parsed_optional_json(_first(props, "fc", "forecast", "rainfall_forecast"))
        features.append(
            {
                "type": "Feature",
                "geometry": feature_geometry,
                "properties": {
                    "warning_id": _text(_first(props, "warning_id", "id")),
                    "severity": _text(_first(props, "severity", "level", "warning_level")),
                    "data_type": _text(_first(props, "data_type", "type")),
                    "data_time": data_time,
                    "message": _text(_first(props, "message", "description", "text")),
                    "forecast": forecast,
                    "source": source.source_name,
                    "source_timestamp": data_time,
                    "fetched_at": timestamp,
                    "cache_status": cache_status,
                    "stale": cache_status == "stale",
                    "ttl_seconds": source.ttl_seconds,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def normalize_city_forecast_features(
    payload: Any, *, cache_status: str, fetched_at: datetime | None = None
) -> dict[str, Any]:
    """Normalize PMD city current conditions and forecast arrays to GeoJSON points."""
    source = pmd_source("monitor_city_forecast")
    timestamp = fetched_at or datetime.now(UTC)
    features = []
    for geometry, raw_props in _station_items(payload):
        props = clean_pmd_value(raw_props)
        if not isinstance(props, dict):
            continue
        point = _point_geometry(geometry, props)
        if point is None:
            continue
        data_time = _text(_first(props, "data_time", "date_time", "datetime", "time"))
        forecast = _parsed_optional_json(_first(props, "fc", "forecast", "forecast_12"))
        features.append(
            {
                "type": "Feature",
                "geometry": point,
                "properties": {
                    "city_id": _text(_first(props, "city_id", "id")),
                    "name": _text(_first(props, "name", "city", "city_name")),
                    "data_time": data_time,
                    "weather_text": _text(_first(props, "weather", "weather_text", "description")),
                    "weather_icon": _text(_first(props, "weather_icon", "icon", "icon_url")),
                    "temperature_c": _number(_first(props, "temperature", "temp", "tem")),
                    "humidity_pct": _number(_first(props, "humidity", "rhu")),
                    "wind_speed_mps": _number(_first(props, "wind_speed", "wspd")),
                    "forecast": forecast if isinstance(forecast, list | dict) else None,
                    "source": source.source_name,
                    "source_timestamp": data_time,
                    "fetched_at": timestamp,
                    "cache_status": cache_status,
                    "stale": cache_status == "stale",
                    "ttl_seconds": source.ttl_seconds,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def clean_pmd_value(value: Any) -> Any:
    """Convert PMD sentinel/fault numeric values to ``None`` recursively."""
    if isinstance(value, dict):
        return {key: clean_pmd_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_pmd_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(clean_pmd_value(item) for item in value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        number = float(value)
        if not math.isfinite(number):
            return None
        if number in SENTINEL_VALUES or abs(number) >= INT32_SENTINEL_MIN_ABS:
            return None
    return value


def parse_json_string(value: Any) -> Any:
    """Parse nested JSON-as-string PMD fields, leaving non-JSON strings unchanged."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def extract_jwt(payload: Any) -> str | None:
    """Find a bearer token across common PMD/vendor login response shapes."""
    if not isinstance(payload, dict):
        return None
    for key in ("token", "access_token", "jwt", "jwtToken", "accessToken", "id_token"):
        value = payload.get(key)
        if isinstance(value, str) and len(value) > 20:
            return value
    data = payload.get("data")
    if isinstance(data, dict):
        return extract_jwt(data)
    if isinstance(data, str) and len(data) > 20:
        return data
    return None


class PmdMonitorClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout_seconds: int = 12,
        session_factory: Callable[[], requests.Session] | None = None,
        now: Callable[[], float] = time.monotonic,
        cache: MutableMapping[str, PmdCacheEntry] | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.pmd_monitor_url or "").rstrip("/")
        self.username = username if username is not None else settings.pmd_monitor_user
        self.password = password if password is not None else settings.pmd_monitor_pass
        self.timeout_seconds = timeout_seconds
        self._session_factory = session_factory or self._make_session
        self._now = now
        self._cache: MutableMapping[str, PmdCacheEntry] = cache if cache is not None else {}
        self._session: requests.Session | None = None
        self._session_expires_at = 0.0
        self._lock = threading.Lock()

    def configured(self) -> bool:
        return bool(self.base_url and self.username and self.password)

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request_json("GET", path, params=params)

    def post_json(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        return self._request_json("POST", path, payload=payload)

    def get_bytes(self, path: str, params: dict[str, Any] | None = None) -> bytes:
        response = self._request("GET", path, params=params)
        return response.content

    def cached(
        self,
        key: str,
        ttl_seconds: int,
        fetch: Callable[[], Any],
        *,
        fallback_key: str | None = None,
    ) -> PmdCacheResult:
        now = self._now()
        entry = self._cache.get(key)
        if entry is not None and entry.expires_at > now:
            return PmdCacheResult(entry.value, "fresh")
        try:
            value = fetch()
        except Exception:
            stale_key = fallback_key or key
            stale = self._cache.get(stale_key)
            if stale is not None:
                return PmdCacheResult(stale.value, "stale")
            raise
        entry = PmdCacheEntry(value=value, expires_at=now + ttl_seconds, stored_at=now)
        self._cache[key] = entry
        if fallback_key is not None:
            self._cache[fallback_key] = PmdCacheEntry(
                value=value, expires_at=now + ttl_seconds * 6, stored_at=now
            )
        return PmdCacheResult(value, "fetched")

    def _make_session(self) -> requests.Session:
        requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
        session = requests.Session()
        session.mount("https://", PmdLegacyTLSAdapter())
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/html, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"{self.base_url}/",
            }
        )
        return session

    def _get_session(self) -> requests.Session:
        if not self.configured():
            raise PmdConfigError("PMD Monitor credentials are not configured")
        now = self._now()
        if self._session is not None and self._session_expires_at > now:
            return self._session
        with self._lock:
            if self._session is not None and self._session_expires_at > now:
                return self._session
            session = self._session_factory()
            self._login(session)
            self._session = session
            self._session_expires_at = now + 3600
            return session

    def _invalidate_session(self) -> None:
        with self._lock:
            self._session = None
            self._session_expires_at = 0.0

    def _login(self, session: requests.Session) -> None:
        response = session.post(
            f"{self.base_url}/user/login",
            json={"username": self.username, "password": self.password},
            timeout=self.timeout_seconds,
            verify=False,
            allow_redirects=False,
        )
        if response.status_code not in (200, 201):
            raise PmdUpstreamError(f"PMD Monitor login failed: HTTP {response.status_code}")
        token = extract_jwt(response.json())
        if token is None:
            raise PmdUpstreamError("PMD Monitor login did not return a bearer token")
        session.headers["Authorization"] = f"Bearer {token}"

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        response = self._request(method, path, params=params, payload=payload)
        try:
            return clean_pmd_value(response.json())
        except ValueError as exc:
            raise PmdUpstreamError(f"PMD Monitor returned non-JSON for {path}") from exc

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        for attempt in range(2):
            session = self._get_session()
            response = session.request(
                method,
                url,
                params=params,
                json=payload,
                timeout=self.timeout_seconds,
                verify=False,
            )
            if response.status_code in (401, 403) and attempt == 0:
                self._invalidate_session()
                continue
            if response.status_code >= 400:
                raise PmdUpstreamError(f"PMD Monitor request failed: HTTP {response.status_code}")
            return response
        raise PmdUpstreamError(f"PMD Monitor authentication failed for {path}")
