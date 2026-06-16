"""``reservoir`` — config-driven core entity (plan 02 §5.1).

Onboarding a reservoir is a config insert (AOI + catchment geometry, FRL, capacity,
orbit/pass, release thresholds), no code change (NFR-SCALE-1). The seasonal rule curve
is the bulletin Normal Storage proxy (ADR-0002), stored per-date in ``ground_truth`` /
ABT, not as a separate curve.
"""

from __future__ import annotations

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class Reservoir(Base):
    __tablename__ = "reservoir"

    reservoir_id: Mapped[str] = mapped_column(Text, primary_key=True)  # slug
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    basin: Mapped[str] = mapped_column(Text, nullable=False)
    dam_point: Mapped[object] = mapped_column(
        Geometry("POINT", srid=4326, spatial_index=False), nullable=False
    )  # seed coordinate (FR-RS-1); GIST index defined explicitly below
    frl_m: Mapped[float] = mapped_column(Numeric(8, 3), nullable=False)
    live_capacity_bcm: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    aoi_geom: Mapped[object] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False
    )  # FRL-extent AOI (FR-RS-1)
    aoi_version: Mapped[str] = mapped_column(Text, nullable=False)
    catchment_geom: Mapped[object | None] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326, spatial_index=False), nullable=True
    )  # upstream area (FR-DE-7); NULL until delineated
    catchment_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    orbit_relative: Mapped[int] = mapped_column(Integer, nullable=False)  # fixed (FR-RS-1)
    pass_direction: Mapped[str] = mapped_column(Text, nullable=False)  # ASC/DESC
    release_thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False)  # FR-ML-3 (D7)
    rating_curve_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("frl_m > 0", name="ck_reservoir_frl_positive"),
        CheckConstraint("live_capacity_bcm > 0", name="ck_reservoir_capacity_positive"),
        CheckConstraint("pass_direction IN ('ASC','DESC')", name="ck_reservoir_pass_dir"),
        Index("idx_reservoir_aoi_geom", "aoi_geom", postgresql_using="gist"),
        Index("idx_reservoir_catchment_geom", "catchment_geom", postgresql_using="gist"),
        Index("idx_reservoir_dam_point", "dam_point", postgresql_using="gist"),
    )
