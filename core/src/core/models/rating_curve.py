"""``rating_curve`` — the blended estimation bridge (FR-GT-4, ADR-0004). Surrogate uuid
PK; unique ``(reservoir_id, version)``; exactly one active curve per reservoir.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class RatingCurve(Base):
    __tablename__ = "rating_curve"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    reservoir_id: Mapped[str] = mapped_column(Text, ForeignKey("reservoir.reservoir_id"))
    version: Mapped[str] = mapped_column(Text, nullable=False)
    fit_type: Mapped[str] = mapped_column(Text, nullable=False)  # empirical/dem_prior/blended
    area_to_storage_params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    area_to_level_params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    curve_points: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    frl_anchor: Mapped[dict] = mapped_column(JSONB, nullable=False)
    observed_range: Mapped[dict] = mapped_column(JSONB, nullable=False)
    extrapolated_range: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    dem_epoch_waterline_m: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    dem_asset_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    fit_metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)  # sedimentation validity
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    mlflow_run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("reservoir_id", "version", name="uq_rating_curve_version"),
        CheckConstraint(
            "fit_type IN ('empirical','dem_prior','blended')", name="ck_rating_curve_fit_type"
        ),
        # Exactly one active curve per reservoir.
        Index(
            "uq_rating_curve_one_active",
            "reservoir_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )
