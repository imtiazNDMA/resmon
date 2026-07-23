"""add reservoir updated_at trigger

Revision ID: a2b4c6d8e0f1
Revises: 9f1a2b3c4d5e
Create Date: 2026-07-16 00:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a2b4c6d8e0f1"
down_revision: str | None = "9f1a2b3c4d5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_reservoir_set_updated_at ON reservoir;"
    )
    op.execute(
        """
        CREATE TRIGGER trg_reservoir_set_updated_at
        BEFORE UPDATE ON reservoir
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_reservoir_set_updated_at ON reservoir;")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")
