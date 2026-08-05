"""``hydrologic_layer_provenance`` — source/version metadata for static map layers."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class HydrologicLayerProvenance(Base):
    __tablename__ = "hydrologic_layer_provenance"

    reservoir_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reservoir.reservoir_id"), primary_key=True
    )
    layer_name: Mapped[str] = mapped_column(Text, primary_key=True)
    source_dataset: Mapped[str] = mapped_column(Text, nullable=False)
    source_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    resolution_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processing_version: Mapped[str] = mapped_column(Text, nullable=False)
    simplification_tolerance_deg: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 8), nullable=True
    )
    projection: Mapped[str] = mapped_column(Text, nullable=False, server_default="EPSG:4326")
    limitations: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("idx_hydrologic_layer_provenance_reservoir", "reservoir_id"),)
