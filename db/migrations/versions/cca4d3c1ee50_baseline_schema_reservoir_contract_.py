"""baseline schema: reservoir + contract tables

Revision ID: cca4d3c1ee50
Revises:
Create Date: 2026-06-16 18:05:59.876126+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cca4d3c1ee50"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostGIS + pgcrypto are owned by the schema, not just first-boot init, so a
    # migration-only bring-up (e.g. ephemeral CI Postgres) is self-contained.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "reservoir",
        sa.Column("reservoir_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("basin", sa.Text(), nullable=False),
        sa.Column("frl_m", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("live_capacity_bcm", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("orbit_relative", sa.Integer(), nullable=False),
        sa.Column("pass_direction", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("pass_direction IN ('ASC','DESC')", name="ck_reservoir_pass_dir"),
        sa.CheckConstraint("frl_m > 0", name="ck_reservoir_frl_positive"),
        sa.CheckConstraint("live_capacity_bcm > 0", name="ck_reservoir_capacity_positive"),
        sa.PrimaryKeyConstraint("reservoir_id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "analytical_base_table",
        sa.Column("reservoir_id", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("abt_version", sa.Text(), nullable=False),
        sa.Column("days_since_bulletin", sa.Integer(), nullable=False),
        sa.Column("days_since_acquisition", sa.Integer(), nullable=False),
        sa.Column("gt_level", sa.Double(), nullable=True),
        sa.Column("gt_live_storage_bcm", sa.Double(), nullable=True),
        sa.Column("gt_pct_filled", sa.Double(), nullable=True),
        sa.Column("frl", sa.Double(), nullable=False),
        sa.Column("live_capacity_bcm", sa.Double(), nullable=False),
        sa.Column("normal_storage_pct", sa.Double(), nullable=True),
        sa.Column("surface_area", sa.Double(), nullable=True),
        sa.Column("area_confidence", sa.Double(), nullable=True),
        sa.Column("derived_volume", sa.Double(), nullable=True),
        sa.Column("derived_level", sa.Double(), nullable=True),
        sa.Column("extraction_method", sa.Text(), nullable=True),
        sa.Column("catchment_precip", sa.Double(), nullable=True),
        sa.Column("antecedent_precip_index", sa.Double(), nullable=True),
        sa.Column("snow_cover_area", sa.Double(), nullable=True),
        sa.Column("swe", sa.Double(), nullable=True),
        sa.Column("degree_day_melt", sa.Double(), nullable=True),
        sa.Column("is_extrapolated", sa.Boolean(), nullable=False),
        sa.Column("residual_vs_ground_truth", sa.Double(), nullable=True),
        sa.Column("source_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("freshness_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("row_quality", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "row_quality IN ('ok','low_confidence','quarantine')", name="ck_abt_row_quality"
        ),
        sa.ForeignKeyConstraint(
            ["reservoir_id"],
            ["reservoir.reservoir_id"],
        ),
        sa.PrimaryKeyConstraint("reservoir_id", "date", "abt_version"),
    )
    op.create_table(
        "forecast_forcing",
        sa.Column("reservoir_id", sa.Text(), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("forecast_precip", sa.Double(), nullable=True),
        sa.Column("forecast_degree_day_melt", sa.Double(), nullable=True),
        sa.Column("gfs_run_cycle", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("horizon >= 1 AND horizon <= 14", name="ck_forecast_horizon_range"),
        sa.ForeignKeyConstraint(
            ["reservoir_id"],
            ["reservoir.reservoir_id"],
        ),
        sa.PrimaryKeyConstraint("reservoir_id", "issue_date", "horizon"),
    )
    op.create_table(
        "observation",
        sa.Column("reservoir_id", sa.Text(), nullable=False),
        sa.Column("acquisition_date", sa.Date(), nullable=False),
        sa.Column("surface_area", sa.Double(), nullable=False),
        sa.Column("area_confidence", sa.Double(), nullable=False),
        sa.Column("derived_volume", sa.Double(), nullable=True),
        sa.Column("derived_level", sa.Double(), nullable=True),
        sa.Column("water_mask_ref", sa.Text(), nullable=False),
        sa.Column("extraction_method", sa.Text(), nullable=False),
        sa.Column("extraction_version", sa.Text(), nullable=False),
        sa.Column("scene_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("orbit_relative", sa.Integer(), nullable=False),
        sa.Column("pass_direction", sa.Text(), nullable=False),
        sa.Column("aoi_version", sa.Text(), nullable=False),
        sa.Column("layover_shadow_fraction", sa.Double(), nullable=False),
        sa.Column("processing_params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("pass_direction IN ('ASC','DESC')", name="ck_observation_pass_dir"),
        sa.CheckConstraint(
            "area_confidence >= 0 AND area_confidence <= 1", name="ck_observation_conf"
        ),
        sa.CheckConstraint(
            "layover_shadow_fraction >= 0 AND layover_shadow_fraction <= 1",
            name="ck_observation_layover",
        ),
        sa.CheckConstraint("surface_area >= 0", name="ck_observation_area_nonneg"),
        sa.ForeignKeyConstraint(
            ["reservoir_id"],
            ["reservoir.reservoir_id"],
        ),
        sa.PrimaryKeyConstraint("reservoir_id", "acquisition_date"),
    )
    # NOTE: PostGIS's spatial_ref_sys is intentionally left untouched (see env.py
    # include_object); the extension owns it.


def downgrade() -> None:
    op.drop_table("observation")
    op.drop_table("forecast_forcing")
    op.drop_table("analytical_base_table")
    op.drop_table("reservoir")
    # ### end Alembic commands ###
