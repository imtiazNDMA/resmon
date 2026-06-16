"""``release_risk`` — the primary output (FR-ML-3, ADR-0001), append-only (trigger in
the migration). PK ``(reservoir_id, run_timestamp)``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Double, ForeignKey, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ReleaseRisk(Base):
    __tablename__ = "release_risk"

    reservoir_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reservoir.reservoir_id"), primary_key=True
    )
    run_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    release_probability: Mapped[float] = mapped_column(Double, nullable=False)  # 0–1
    risk_level: Mapped[str] = mapped_column(Text, nullable=False)  # Low/Watch/Warning/Imminent
    estimated_lead_time_days: Mapped[float | None] = mapped_column(Double, nullable=True)
    contributing_factors: Mapped[dict] = mapped_column(JSONB, nullable=False)  # explainability
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("model_version.id"), nullable=False
    )
    input_abt_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "release_probability >= 0 AND release_probability <= 1", name="ck_release_prob"
        ),
        CheckConstraint("risk_level IN ('Low','Watch','Warning','Imminent')", name="ck_risk_level"),
    )
