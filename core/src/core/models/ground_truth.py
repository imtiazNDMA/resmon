"""``ground_truth`` — bulletin time series (§6.2). Bootstrap corpus only (ADR-0005):
trains/backtests the system, never available in production. PK ``(reservoir_id, date)``.
``numeric`` preserves raw source fidelity (plan R-7); contract tables use ``float``.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class GroundTruth(Base):
    __tablename__ = "ground_truth"

    reservoir_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reservoir.reservoir_id"), primary_key=True
    )
    date: Mapped[date] = mapped_column(primary_key=True)  # bulletin date (IST)
    level_m: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    live_storage_bcm: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    pct_filled: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    frl_m: Mapped[float] = mapped_column(Numeric(8, 3), nullable=False)
    live_capacity_bcm: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    normal_storage_pct: Mapped[float | None] = mapped_column(
        Numeric(6, 3), nullable=True
    )  # rule-curve proxy (ADR-0002)
    benefits_irr_cca: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    benefits_hydel_mw: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    source_pdf: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_quality: Mapped[str] = mapped_column(Text, nullable=False, server_default="ok")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # Hard CHECKs only on physically-impossible values; soft range violations route
        # to row_quality='quarantine' via the loader (FR-DE-4, plan R-2).
        CheckConstraint("pct_filled IS NULL OR pct_filled >= 0", name="ck_gt_pct_nonneg"),
        CheckConstraint("level_m IS NULL OR level_m >= 0", name="ck_gt_level_nonneg"),
        CheckConstraint(
            "row_quality IN ('ok','low_confidence','quarantine')", name="ck_gt_row_quality"
        ),
    )
