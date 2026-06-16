"""Pydantic schemas for ``observation`` (contract §1)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ObservationUpsert(BaseModel):
    """Write contract for an Observation row (RS → DE)."""

    reservoir_id: str
    acquisition_date: date
    surface_area: float = Field(ge=0)  # km²
    area_confidence: float = Field(ge=0, le=1)
    derived_volume: float | None = None  # BCM
    derived_level: float | None = None  # m
    water_mask_ref: str
    extraction_method: str  # kmeans/otsu/unet/stub
    extraction_version: str
    scene_ids: list[str]
    orbit_relative: int
    pass_direction: str = Field(pattern="^(ASC|DESC)$")
    aoi_version: str
    layover_shadow_fraction: float = Field(ge=0, le=1)
    processing_params: dict


class ObservationRead(ObservationUpsert):
    model_config = ConfigDict(from_attributes=True)
    created_at: datetime
