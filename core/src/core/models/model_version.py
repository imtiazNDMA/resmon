"""``model_version`` — minimal mirror of the MLflow registry (FR-ML-4) so prediction /
release-risk provenance survives MLflow downtime. Surrogate uuid PK.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ModelVersion(Base):
    __tablename__ = "model_version"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    mlflow_run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_stage: Mapped[str] = mapped_column(Text, nullable=False)  # staging/production/archived
    trained_on_abt_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("model_name", "version", name="uq_model_version"),
        CheckConstraint(
            "model_stage IN ('staging','production','archived')", name="ck_model_stage"
        ),
    )
