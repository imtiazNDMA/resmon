"""Pydantic schema for an ``analytical_base_table`` row (contract §2, v2)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class AnalyticalBaseTableRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # keys & alignment
    reservoir_id: str
    date: date
    abt_version: str
    days_since_bulletin: int
    days_since_acquisition: int

    # ground truth
    gt_level: float | None = None
    gt_live_storage_bcm: float | None = None
    gt_pct_filled: float | None = None
    frl: float
    live_capacity_bcm: float
    normal_storage_pct: float | None = None

    # satellite-derived
    surface_area: float | None = None
    area_confidence: float | None = None
    derived_volume: float | None = None
    derived_level: float | None = None
    extraction_method: str | None = None

    # catchment forcing
    catchment_precip: float | None = None
    antecedent_precip_index: float | None = None
    snow_cover_area: float | None = None
    swe: float | None = None
    degree_day_melt: float | None = None

    # provenance, quality & target
    is_extrapolated: bool
    residual_vs_ground_truth: float | None = None
    source_versions: dict
    freshness_flags: dict
    row_quality: str = Field(pattern="^(ok|low_confidence|quarantine)$")
    created_at: datetime | None = None
