"""``prediction`` — 1–14 day forecasts (FR-ML-2/5), append-only (NFR-REL-5; trigger in
the migration). PK ``(reservoir_id, run_timestamp, horizon_date)``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Double, ForeignKey, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class Prediction(Base):
    __tablename__ = "prediction"

    reservoir_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reservoir.reservoir_id"), primary_key=True
    )
    run_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    horizon_date: Mapped[date] = mapped_column(Date, primary_key=True)  # target IST date
    predicted_level_m: Mapped[float | None] = mapped_column(Double, nullable=True)
    predicted_volume_bcm: Mapped[float | None] = mapped_column(Double, nullable=True)
    predicted_pct_filled: Mapped[float | None] = mapped_column(Double, nullable=True)
    interval_low: Mapped[float | None] = mapped_column(Double, nullable=True)  # conformal
    interval_high: Mapped[float | None] = mapped_column(Double, nullable=True)
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("model_version.id"), nullable=False
    )
    input_abt_version: Mapped[str] = mapped_column(Text, nullable=False)  # FR-ABT-4
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
