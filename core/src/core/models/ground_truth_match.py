"""``ground_truth_match`` — nearest-imagery pairing + indirect validation (FR-GT-1..3).
AC-2 evidence. PK ``(reservoir_id, gt_date, extraction_version)`` (a GT date may be
re-matched by a new extractor).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class GroundTruthMatch(Base):
    __tablename__ = "ground_truth_match"

    reservoir_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reservoir.reservoir_id"), primary_key=True
    )
    gt_date: Mapped[date] = mapped_column(Date, primary_key=True)
    extraction_version: Mapped[str] = mapped_column(Text, primary_key=True)
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    time_gap_days: Mapped[int] = mapped_column(Integer, nullable=False)  # FR-GT-1
    scene_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    extracted_area: Mapped[float] = mapped_column(Double, nullable=False)  # km²
    area_confidence: Mapped[float] = mapped_column(Double, nullable=False)  # 0–1
    extraction_method: Mapped[str] = mapped_column(Text, nullable=False)
    rating_curve_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    derived_volume: Mapped[float | None] = mapped_column(Double, nullable=True)  # BCM
    derived_level: Mapped[float | None] = mapped_column(Double, nullable=True)  # m
    derived_pct_filled: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    residual_vs_ground_truth: Mapped[float | None] = mapped_column(Double, nullable=True)  # %
    is_weak_label: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )  # FR-GT-6
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["reservoir_id", "gt_date"],
            ["ground_truth.reservoir_id", "ground_truth.date"],
            name="fk_gtmatch_ground_truth",
        ),
    )
