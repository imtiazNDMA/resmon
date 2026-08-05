"""district boundary table

Revision ID: f1a2b3c4d5e6
Revises: e8a7c6d5b4f3
Create Date: 2026-08-05
"""

from __future__ import annotations

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "e8a7c6d5b4f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "district_boundary",
        sa.Column("district_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("source_dataset", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(
                geometry_type="MULTIPOLYGON",
                srid=4326,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("district_id"),
    )
    op.create_index("idx_district_boundary_geom", "district_boundary", ["geom"], postgresql_using="gist")


def downgrade() -> None:
    op.drop_index("idx_district_boundary_geom", table_name="district_boundary", postgresql_using="gist")
    op.drop_table("district_boundary")
