"""catchment_flowline table

Revision ID: d4f6a8b2c9e1
Revises: b7d3e5f9c1a2
Create Date: 2026-08-05 00:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

revision: str = "d4f6a8b2c9e1"
down_revision: str | None = "b7d3e5f9c1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catchment_flowline",
        sa.Column("reservoir_id", sa.Text(), nullable=False),
        sa.Column("flowline_id", sa.BigInteger(), nullable=False),
        sa.Column("downstream_id", sa.BigInteger(), nullable=True),
        sa.Column("stream_order", sa.Integer(), nullable=True),
        sa.Column("upstream_area_km2", sa.Numeric(12, 3), nullable=True),
        sa.Column("length_km", sa.Numeric(10, 3), nullable=True),
        sa.Column("is_main_stem", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "geom",
            Geometry(
                geometry_type="MULTILINESTRING",
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=False,
        ),
        sa.Column("source_dataset", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["reservoir_id"], ["reservoir.reservoir_id"]),
        sa.PrimaryKeyConstraint("reservoir_id", "flowline_id"),
    )
    op.create_index(
        "idx_catchment_flowline_reservoir",
        "catchment_flowline",
        ["reservoir_id"],
        unique=False,
    )
    op.create_index(
        "idx_catchment_flowline_geom",
        "catchment_flowline",
        ["geom"],
        unique=False,
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_catchment_flowline_geom", table_name="catchment_flowline", postgresql_using="gist"
    )
    op.drop_index("idx_catchment_flowline_reservoir", table_name="catchment_flowline")
    op.drop_table("catchment_flowline")
