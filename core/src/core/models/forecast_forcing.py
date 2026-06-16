"""``forecast_forcing`` — Data-Engineering → ML. Mirrors frozen contract §3 (v2).

Horizon-indexed GFS forecast features, point-in-time per ``issue_date``. PK
``(reservoir_id, issue_date, horizon)``. Columns 1:1 with the contract §3; ``created_at``
is an additive provenance column.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
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


class ForecastForcing(Base):
    __tablename__ = "forecast_forcing"

    reservoir_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reservoir.reservoir_id"), primary_key=True
    )
    issue_date: Mapped[date] = mapped_column(Date, primary_key=True)  # IST, as-of
    horizon: Mapped[int] = mapped_column(Integer, primary_key=True)  # days, 1–14
    forecast_precip: Mapped[float | None] = mapped_column(Double, nullable=True)  # mm/day
    forecast_degree_day_melt: Mapped[float | None] = mapped_column(Double, nullable=True)  # mm/day
    gfs_run_cycle: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_versions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # additive provenance (not in contract column set)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("horizon >= 1 AND horizon <= 14", name="ck_forecast_horizon_range"),
    )
