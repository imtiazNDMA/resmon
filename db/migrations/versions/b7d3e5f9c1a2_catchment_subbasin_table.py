"""catchment_subbasin table (un-dissolved upstream basins)

Revision ID: b7d3e5f9c1a2
Revises: a2b4c6d8e0f1
Create Date: 2026-08-04 00:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

revision: str = "b7d3e5f9c1a2"
down_revision: str | None = "a2b4c6d8e0f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catchment_subbasin",
        sa.Column("reservoir_id", sa.Text(), nullable=False),
        sa.Column("hybas_id", sa.BigInteger(), nullable=False),
        sa.Column("next_down", sa.BigInteger(), nullable=False),
        sa.Column("is_headwater", sa.Boolean(), nullable=False),
        sa.Column(
            "geom",
            Geometry(
                geometry_type="MULTIPOLYGON",
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=False,
        ),
        sa.Column("catchment_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["reservoir_id"], ["reservoir.reservoir_id"]),
        sa.PrimaryKeyConstraint("reservoir_id", "hybas_id"),
    )
    op.create_index(
        "idx_catchment_subbasin_geom",
        "catchment_subbasin",
        ["geom"],
        unique=False,
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_catchment_subbasin_geom", table_name="catchment_subbasin", postgresql_using="gist"
    )
    op.drop_table("catchment_subbasin")
