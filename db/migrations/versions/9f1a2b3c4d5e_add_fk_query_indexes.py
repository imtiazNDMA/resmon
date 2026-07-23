"""add FK query indexes

Revision ID: 9f1a2b3c4d5e
Revises: 7c4e9a1d2b6f
Create Date: 2026-07-16 00:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "9f1a2b3c4d5e"
down_revision: str | None = "7c4e9a1d2b6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("idx_rating_curve_reservoir", "rating_curve", ["reservoir_id"])
    op.create_index("idx_prediction_model_version", "prediction", ["model_version_id"])
    op.create_index("idx_release_risk_model_version", "release_risk", ["model_version_id"])
    op.create_index("idx_pipeline_run_reservoir", "pipeline_run", ["reservoir_id"])


def downgrade() -> None:
    op.drop_index("idx_pipeline_run_reservoir", table_name="pipeline_run")
    op.drop_index("idx_release_risk_model_version", table_name="release_risk")
    op.drop_index("idx_prediction_model_version", table_name="prediction")
    op.drop_index("idx_rating_curve_reservoir", table_name="rating_curve")
