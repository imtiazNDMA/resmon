"""``catchment_forcing`` — per-reservoir per-date catchment-aggregated forcing (FR-DE-7..11).
Mirrors the ABT forcing block; includes ``evaporation`` (contract v3, D6).
PK ``(reservoir_id, date)``.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import DateTime, Double, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class CatchmentForcing(Base):
    __tablename__ = "catchment_forcing"

    reservoir_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reservoir.reservoir_id"), primary_key=True
    )
    date: Mapped[date] = mapped_column(primary_key=True)  # IST
    catchment_precip: Mapped[float | None] = mapped_column(Double, nullable=True)  # mm/day
    antecedent_precip_index: Mapped[float | None] = mapped_column(Double, nullable=True)  # mm
    snow_cover_area: Mapped[float | None] = mapped_column(Double, nullable=True)  # 0–1
    swe: Mapped[float | None] = mapped_column(Double, nullable=True)  # mm
    degree_day_melt: Mapped[float | None] = mapped_column(Double, nullable=True)  # mm/day
    evaporation: Mapped[float | None] = mapped_column(Double, nullable=True)  # mm/day (v3, D6)
    source_versions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    freshness_flags: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
