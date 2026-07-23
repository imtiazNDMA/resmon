"""Catchment-aggregated Open-Meteo daily forcings for modeling.

The API is sampled at a regular grid clipped to each catchment, then averaged/summed
across all sampled points. The model sees catchment aggregates, never a single-point
weather value.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

_ROOT = Path(__file__).resolve().parents[4]
_CACHE_ROOT = _ROOT / ".cache" / "openmeteo-forcing-v3"
_BATCH_SIZE = 80
_DAILY_VARIABLES = "temperature_2m_mean,precipitation_sum,rain_sum,snowfall_sum"


class OpenMeteoForcingUnavailable(RuntimeError):
    """Open-Meteo forcing could not be fetched; caller should keep NULLs, not fake zeros."""


def _cache_path(reservoir_id: str, start: date, end: date) -> Path:
    safe = "".join(ch for ch in reservoir_id if ch.isalnum() or ch in "_-")
    return _CACHE_ROOT / safe / f"{start.isoformat()}_{end.isoformat()}.json"


def _samples(session: Session, reservoir_id: str, scale: int = 4, max_points: int = 80) -> list[dict]:
    rows = (
        session.execute(
            text(
                """
                WITH geom AS (
                    SELECT catchment_geom AS g FROM reservoir
                    WHERE reservoir_id = :r AND catchment_geom IS NOT NULL
                ), bounds AS (
                    SELECT
                        floor(ST_XMin(ST_Extent(g)) * :scale)::int AS minx,
                        ceil(ST_XMax(ST_Extent(g)) * :scale)::int AS maxx,
                        floor(ST_YMin(ST_Extent(g)) * :scale)::int AS miny,
                        ceil(ST_YMax(ST_Extent(g)) * :scale)::int AS maxy
                    FROM geom
                ), grid AS (
                    SELECT x / CAST(:scale AS float) AS lon, y / CAST(:scale AS float) AS lat
                    FROM bounds,
                         generate_series(minx, maxx) AS x,
                         generate_series(miny, maxy) AS y
                )
                SELECT lat, lon
                FROM grid, geom
                WHERE ST_Intersects(g, ST_SetSRID(ST_MakePoint(lon, lat), 4326))
                ORDER BY lat, lon
                LIMIT :max_points
                """
            ),
            {"r": reservoir_id, "scale": scale, "max_points": max_points},
        )
        .mappings()
        .all()
    )
    return [{"lat": float(r["lat"]), "lon": float(r["lon"])} for r in rows]


def _read_cache(path: Path) -> list[dict] | None:
    if not path.exists():
        return None
    try:
        return list(json.loads(path.read_text(encoding="utf-8"))["responses"])
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None


def _write_cache(path: Path, responses: list[dict]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"fetched_at": datetime.now(UTC).isoformat(), "responses": responses}),
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError:
        return


def _endpoint_for(end: date) -> str:
    recent_cutoff = datetime.now(UTC).date() - timedelta(days=5)
    if end >= recent_cutoff:
        return "https://api.open-meteo.com/v1/forecast"
    return "https://archive-api.open-meteo.com/v1/archive"


def _fetch(samples: list[dict], start: date, end: date) -> list[dict]:
    responses: list[dict] = []
    for offset in range(0, len(samples), _BATCH_SIZE):
        batch = samples[offset : offset + _BATCH_SIZE]
        params = {
            "latitude": ",".join(f"{p['lat']:.5f}" for p in batch),
            "longitude": ",".join(f"{p['lon']:.5f}" for p in batch),
            "daily": _DAILY_VARIABLES,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "timezone": "UTC",
        }
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            for attempt in range(3):
                resp = client.get(_endpoint_for(end), params=params)
                if resp.status_code != 429:
                    resp.raise_for_status()
                    break
                if attempt == 2:
                    resp.raise_for_status()
                time.sleep(30 * (attempt + 1))
        payload = resp.json()
        if isinstance(payload, dict):
            responses.append(payload)
        elif isinstance(payload, list):
            responses.extend(item for item in payload if isinstance(item, dict))
    return responses


def catchment_daily_forcing(
    session: Session, reservoir_id: str, start: date, end: date
) -> pd.DataFrame:
    """Return daily catchment aggregates from gridded Open-Meteo point samples.

    Columns are model-ready daily catchment means/sums:
    precipitation/rain/snowfall in mm/day, mean temperature in deg C, max wind in km/h.
    ``swe`` stores a cumulative snowfall-depth proxy in mm because the current schema has
    no separate snow-depth column. It is not measured snow-water-equivalent.
    """
    points = _samples(session, reservoir_id)
    if not points:
        raise OpenMeteoForcingUnavailable(f"no catchment sample points for {reservoir_id}")
    path = _cache_path(reservoir_id, start, end)
    responses = _read_cache(path)
    if responses is None:
        try:
            responses = _fetch(points, start, end)
        except Exception as exc:
            raise OpenMeteoForcingUnavailable(str(exc)) from exc
        _write_cache(path, responses)

    frames = []
    for item in responses:
        daily = item.get("daily") if isinstance(item.get("daily"), dict) else {}
        if not daily.get("time"):
            continue
        frames.append(pd.DataFrame(daily).assign(sample_weight=1.0))
    if not frames:
        raise OpenMeteoForcingUnavailable(f"Open-Meteo returned no daily rows for {reservoir_id}")

    raw = pd.concat(frames, ignore_index=True)
    grouped = raw.groupby("time", dropna=False).mean(numeric_only=True)
    grouped.index = pd.to_datetime(grouped.index)
    out = pd.DataFrame(index=grouped.index)
    out["catchment_precip"] = grouped.get("precipitation_sum")
    out["rain_sum"] = grouped.get("rain_sum")
    out["snowfall"] = grouped.get("snowfall_sum")
    out["mean_temp_c"] = grouped.get("temperature_2m_mean")
    out["degree_day_melt"] = (out["mean_temp_c"] - 0.0).clip(lower=0) * 4.0
    out["snow_cover_area"] = (
        raw.assign(has_snow=lambda d: d["snowfall_sum"].fillna(0) > 0)
        .groupby("time")["has_snow"]
        .mean()
        .rename(index=pd.Timestamp)
        .reindex(out.index)
        .to_numpy()
    )
    out["swe"] = (out["snowfall"].fillna(0) * 10.0).cumsum()
    return out
