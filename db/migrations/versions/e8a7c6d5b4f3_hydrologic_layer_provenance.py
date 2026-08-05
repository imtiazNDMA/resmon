"""hydrologic layer provenance table

Revision ID: e8a7c6d5b4f3
Revises: d4f6a8b2c9e1
Create Date: 2026-08-05 00:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8a7c6d5b4f3"
down_revision: str | None = "d4f6a8b2c9e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hydrologic_layer_provenance",
        sa.Column("reservoir_id", sa.Text(), nullable=False),
        sa.Column("layer_name", sa.Text(), nullable=False),
        sa.Column("source_dataset", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=True),
        sa.Column("source_date", sa.Date(), nullable=True),
        sa.Column("resolution_m", sa.Numeric(10, 3), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_version", sa.Text(), nullable=False),
        sa.Column("simplification_tolerance_deg", sa.Numeric(10, 8), nullable=True),
        sa.Column("projection", sa.Text(), server_default="EPSG:4326", nullable=False),
        sa.Column("limitations", sa.Text(), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["reservoir_id"], ["reservoir.reservoir_id"]),
        sa.PrimaryKeyConstraint("reservoir_id", "layer_name"),
    )
    op.create_index(
        "idx_hydrologic_layer_provenance_reservoir",
        "hydrologic_layer_provenance",
        ["reservoir_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_hydrologic_layer_provenance_reservoir",
        table_name="hydrologic_layer_provenance",
    )
    op.drop_table("hydrologic_layer_provenance")
