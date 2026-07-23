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


class WaterExtentProperties(BaseModel):
    reservoir_id: str
    name: str
    surface_area_km2: float
    acquisition_date: date


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
