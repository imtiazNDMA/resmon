"""``reservoir_capacity_history`` — time-varying capacity/FRL from sedimentation (§10)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ReservoirCapacityHistory(Base):
    __tablename__ = "reservoir_capacity_history"

    reservoir_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reservoir.reservoir_id"), primary_key=True
    )
    valid_from: Mapped[date] = mapped_column(primary_key=True)
    live_capacity_bcm: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    frl_m: Mapped[float] = mapped_column(Numeric(8, 3), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # bulletin / re-survey
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("live_capacity_bcm > 0", name="ck_capacity_history_positive"),
    )
