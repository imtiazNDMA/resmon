"""``pipeline_run`` — run-history / observability + idempotency metadata (NFR-REL-2,
FR-API-5). Surrogate uuid PK.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class PipelineRun(Base):
    __tablename__ = "pipeline_run"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    pipeline: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # remote_sensing/data_engineering/ml
    reservoir_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("reservoir.reservoir_id"), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)  # running/success/failed/quarantined
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract_version: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "pipeline IN ('remote_sensing','data_engineering','ml')", name="ck_pipeline_name"
        ),
        CheckConstraint(
            "status IN ('running','success','failed','quarantined')", name="ck_pipeline_status"
        ),
    )
