"""Typed response models (D5) — the OpenAPI contract for every public route.

Postgres ``numeric`` values arrive as ``Decimal``; declaring the fields as ``float``
makes Pydantic coerce them to JSON numbers, replacing the hand-rolled coercion the
repositories used to do.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

# --- Reservoirs -----------------------------------------------------------------


class ReservoirSummary(BaseModel):
    reservoir_id: str
    name: str
    basin: str
    frl_m: float
    live_capacity_bcm: float
    is_active: bool


class ReservoirDetail(ReservoirSummary):
    orbit_relative: int
    pass_direction: str
    aoi_version: str


class ReservoirStatus(BaseModel):
    reservoir_id: str
    as_of: date
    pct_filled: float
    level_m: float | None
    live_storage_bcm: float | None
    risk_level: str | None
    release_probability: float | None
    estimated_lead_time_days: float | None
    last_acquisition_date: date | None
    data_age_days: int | None
    stale: bool


class TimeseriesPoint(BaseModel):
    date: date
    pct_filled: float
    level_m: float | None
    live_storage_bcm: float | None
    normal_storage_pct: float | None


class AcquisitionOut(BaseModel):
    date: str
    historical_date: str | None
    area_km2: float
    confidence: float
    live_storage_bcm: float | None
    level_m: float | None
    pct_filled: float | None
    surface_area_correlation: float | None
    is_extrapolated: bool


class CurrentEstimateOut(BaseModel):
    reservoir_id: str
    acquisition_date: str
    area_km2: float
    confidence: float
    live_storage_bcm: float
    level_m: float
    pct_filled: float
    is_extrapolated: bool
    rating_curve_version: str | None
    rating_curve_fit_type: str | None
    catchment_precip: float | None
    antecedent_precip_index: float | None
    snow_cover_area: float | None
    degree_day_melt: float | None
    evaporation: float | None


class SarTileOut(BaseModel):
    tile_url: str
    expires_at: str
    composite: str
    source: Literal["local", "earth_engine"]


class SarAssetManifestEntryOut(BaseModel):
    reservoir_id: str
    acquisition_date: date
    scene_id: str
    composites: list[str]
    bounds: list[float] | None
    min_zoom: int
    max_zoom: int


class SarTileMetricsOut(BaseModel):
    rendered_cache_hits: int
    local_asset_hits: int
    local_renders: int
    earth_engine_fallbacks: int
    tile_render_latency_ms_total: float
    tile_render_latency_ms_avg: float


class RainfallPointOut(BaseModel):
    date: str
    precip_mm: float | None


class MetForcingOut(BaseModel):
    reservoir_id: str
    as_of: str | None
    precip_7d_mm: float | None
    antecedent_precip_index_mm: float | None
    snow_cover_pct: float | None
    degree_day_melt_mm_day: float | None
    evaporation_mm_day: float | None


# --- Forecast / risk --------------------------------------------------------------


class ForecastPoint(BaseModel):
    horizon_date: date
    predicted_pct_filled: float | None
    interval_low: float | None
    interval_high: float | None


class ForecastResponse(BaseModel):
    reservoir_id: str
    horizon: int
    points: list[ForecastPoint]


class ReleaseRiskEntry(BaseModel):
    reservoir_id: str
    risk_level: str
    release_probability: float
    estimated_lead_time_days: float | None
    run_timestamp: datetime


# --- Accuracy ----------------------------------------------------------------------


class RatingCurveAccuracy(BaseModel):
    reservoir_id: str
    version: str
    fit_metrics: dict[str, Any]


class ForecasterAccuracy(BaseModel):
    version: str
    metrics: dict[str, Any] | None


class AccuracyReport(BaseModel):
    rating_curves: list[RatingCurveAccuracy]
    forecaster: ForecasterAccuracy | None
    note: str


# --- GeoJSON -----------------------------------------------------------------------


class Feature[PropsT: BaseModel](BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any] | None
    properties: PropsT


class FeatureCollection[PropsT: BaseModel](BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[Feature[PropsT]]


class AoiProperties(BaseModel):
    reservoir_id: str
    name: str
    aoi_version: str


class CatchmentProperties(BaseModel):
    reservoir_id: str
    name: str
    version: str | None


class SubBasinProperties(BaseModel):
    reservoir_id: str
    hybas_id: int
    next_down: int
    is_headwater: bool
    version: str


class FlowEdgeProperties(BaseModel):
    reservoir_id: str
    from_hybas_id: int
    to_hybas_id: int | None
    is_headwater: bool
    distance_to_reservoir_km: float | None
    routing_lag_days: float | None
    version: str


class FlowlineProperties(BaseModel):
    reservoir_id: str
    flowline_id: int
    downstream_id: int | None
    stream_order: int | None
    upstream_area_km2: float | None
    length_km: float | None
    is_main_stem: bool
    source_dataset: str
    version: str


class HydrologicLayerProvenanceOut(BaseModel):
    reservoir_id: str
    layer_name: str
    source_dataset: str
    source_version: str | None
    source_date: date | None
    resolution_m: float | None
    processed_at: datetime
    processing_version: str
    simplification_tolerance_deg: float | None
    projection: str
    limitations: str
    metadata: dict[str, Any]


class WaterExtentProperties(BaseModel):
    reservoir_id: str
    name: str
    surface_area_km2: float
    acquisition_date: date


class DistrictBoundaryProperties(BaseModel):
    district_id: int
    bbox: list[float]


class PmdStationObservationProperties(BaseModel):
    station_id: str | None
    code: str | None
    name: str | None
    station_type: str | None
    date_time: str | None
    temperature_c: float | None
    humidity_pct: float | None
    pressure_hpa: float | None
    wind_speed_mps: float | None
    wind_direction_deg: float | None
    rain_1h_mm: float | None
    rain_6h_mm: float | None
    rain_24h_mm: float | None
    visibility_km: float | None
    status: bool | None
    warn_temp: str | None
    warn_wind: str | None
    warn_rain: str | None
    warn_vis: str | None
    source: str
    source_timestamp: str | None
    fetched_at: datetime
    cache_status: str
    stale: bool
    ttl_seconds: int


class ReservoirMarkerProperties(BaseModel):
    reservoir_id: str
    name: str
    frl_m: float
    risk_level: str | None
    release_probability: float | None


# --- Health ------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, str]
    staleness_threshold_days: int
