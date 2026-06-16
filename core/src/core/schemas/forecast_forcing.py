"""Pydantic schema for ``forecast_forcing`` (contract §3, horizon-keyed)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ForecastForcingRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reservoir_id: str
    issue_date: date
    horizon: int = Field(ge=1, le=14)
    forecast_precip: float | None = None  # mm/day
    forecast_degree_day_melt: float | None = None  # mm/day
    gfs_run_cycle: datetime
    source_versions: dict
    created_at: datetime | None = None
