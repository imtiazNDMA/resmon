"""``observation`` — Remote-Sensing → Data-Engineering. Mirrors frozen contract §1.

One row per SAR acquisition over an AOI. PK ``(reservoir_id, acquisition_date)`` →
idempotent upsert. Columns are 1:1 with ``docs/contracts/observation-and-abt.md`` §1;
``created_at`` is an additive provenance column (allowed extra in the parity test).
"""

from __future__ import annotations

from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class Observation(Base):
    __tablename__ = "observation"

    reservoir_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reservoir.reservoir_id"), primary_key=True
    )
    acquisition_date: Mapped[date] = mapped_column(Date, primary_key=True)  # IST
    surface_area: Mapped[float] = mapped_column(Double, nullable=False)  # km²
    area_confidence: Mapped[float] = mapped_column(Double, nullable=False)  # 0–1 (contract: float)
    derived_volume: Mapped[float | None] = mapped_column(Double, nullable=True)  # BCM
    derived_level: Mapped[float | None] = mapped_column(Double, nullable=True)  # m
    water_mask_ref: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_method: Mapped[str] = mapped_column(Text, nullable=False)  # kmeans/otsu/unet/stub
    extraction_version: Mapped[str] = mapped_column(Text, nullable=False)
    scene_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    orbit_relative: Mapped[int] = mapped_column(Integer, nullable=False)
    pass_direction: Mapped[str] = mapped_column(Text, nullable=False)  # ASC/DESC
    aoi_version: Mapped[str] = mapped_column(Text, nullable=False)
    layover_shadow_fraction: Mapped[float] = mapped_column(
        Double, nullable=False
    )  # 0–1 (contract: float)
    processing_params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # additive provenance / served-overlay columns (not in contract column set; allow-listed)
    water_mask_geom: Mapped[object | None] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326, spatial_index=False), nullable=True
    )  # vectorised water extent for the Leaflet overlay (FR-API-2)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("surface_area >= 0", name="ck_observation_area_nonneg"),
        CheckConstraint(
            "area_confidence >= 0 AND area_confidence <= 1", name="ck_observation_conf"
        ),
        CheckConstraint(
            "layover_shadow_fraction >= 0 AND layover_shadow_fraction <= 1",
            name="ck_observation_layover",
        ),
        CheckConstraint("pass_direction IN ('ASC','DESC')", name="ck_observation_pass_dir"),
        Index(
            "idx_observation_water_mask_geom",
            "water_mask_geom",
            postgresql_using="gist",
        ),
    )
