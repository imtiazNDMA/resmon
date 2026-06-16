"""``analytical_base_table`` — Data-Engineering → ML. Mirrors frozen contract §2 (v2).

One row per ``(reservoir_id, date)`` on a continuous daily IST grid. ``abt_version`` is
added to the PK (plan 02 §5.9, the one deliberate extension) so immutable snapshots
coexist; the ``abt_current`` view exposes the contract's ``(reservoir_id, date)`` grain.
Forecast forcing is NOT denormalised here — ML joins ``forecast_forcing`` on
``issue_date = date`` (contract §3, v2). All ``float`` columns are DOUBLE PRECISION per
the contract; ``created_at`` is the only additive (non-contract) column.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class AnalyticalBaseTable(Base):
    __tablename__ = "analytical_base_table"

    # --- keys & alignment ---
    reservoir_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reservoir.reservoir_id"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)  # continuous daily IST
    abt_version: Mapped[str] = mapped_column(Text, primary_key=True)  # snapshot (PK extension)
    days_since_bulletin: Mapped[int] = mapped_column(Integer, nullable=False)
    days_since_acquisition: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- ground truth (populated on bulletin dates) ---
    gt_level: Mapped[float | None] = mapped_column(Double, nullable=True)  # m
    gt_live_storage_bcm: Mapped[float | None] = mapped_column(Double, nullable=True)  # BCM
    gt_pct_filled: Mapped[float | None] = mapped_column(Double, nullable=True)  # %
    frl: Mapped[float] = mapped_column(Double, nullable=False)  # m
    live_capacity_bcm: Mapped[float] = mapped_column(Double, nullable=False)  # BCM
    normal_storage_pct: Mapped[float | None] = mapped_column(
        Double, nullable=True
    )  # rule-curve proxy

    # --- satellite-derived (populated on acquisition dates) ---
    surface_area: Mapped[float | None] = mapped_column(Double, nullable=True)  # km²
    area_confidence: Mapped[float | None] = mapped_column(Double, nullable=True)  # 0–1
    derived_volume: Mapped[float | None] = mapped_column(Double, nullable=True)  # BCM
    derived_level: Mapped[float | None] = mapped_column(Double, nullable=True)  # m
    extraction_method: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- catchment forcing (native daily) ---
    catchment_precip: Mapped[float | None] = mapped_column(Double, nullable=True)  # mm/day
    antecedent_precip_index: Mapped[float | None] = mapped_column(Double, nullable=True)  # mm
    snow_cover_area: Mapped[float | None] = mapped_column(Double, nullable=True)  # 0–1
    swe: Mapped[float | None] = mapped_column(Double, nullable=True)  # mm
    degree_day_melt: Mapped[float | None] = mapped_column(Double, nullable=True)  # mm/day
    evaporation: Mapped[float | None] = mapped_column(Double, nullable=True)  # mm/day (v3, D6)

    # --- provenance, quality & target ---
    is_extrapolated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    residual_vs_ground_truth: Mapped[float | None] = mapped_column(Double, nullable=True)  # %
    source_versions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    freshness_flags: Mapped[dict] = mapped_column(JSONB, nullable=False)
    row_quality: Mapped[str] = mapped_column(Text, nullable=False)
    # additive provenance (not in contract column set)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "row_quality IN ('ok','low_confidence','quarantine')", name="ck_abt_row_quality"
        ),
    )
