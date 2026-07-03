"""abt_current ordering by created_at + TRUNCATE guards on append-only tables

``abt_current`` used to pick the latest snapshot by ``abt_version DESC`` — a lexicographic
TEXT sort that breaks at double digits (``abt_v9`` > ``abt_v10``). Order by ``created_at``
instead (D6). Also extend the append-only guarantee (NFR-REL-5) with BEFORE TRUNCATE
statement triggers on ``prediction`` and ``release_risk`` (D10), mirroring the existing
UPDATE/DELETE row triggers from cb96ab2f3b5e.

Revision ID: 7c4e9a1d2b6f
Revises: 35175aee5c62
Create Date: 2026-07-03 00:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "7c4e9a1d2b6f"
down_revision: str | None = "35175aee5c62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # abt_current: latest snapshot per (reservoir_id, date) by creation time (D6).
    op.execute("DROP VIEW IF EXISTS abt_current;")
    op.execute(
        """
        CREATE VIEW abt_current AS
        SELECT DISTINCT ON (reservoir_id, date) *
        FROM analytical_base_table
        ORDER BY reservoir_id, date, created_at DESC;
        """
    )

    # Append-only hardening (D10): TRUNCATE would silently bypass the row-level
    # UPDATE/DELETE triggers; forbid it with statement-level triggers.
    op.execute(
        "CREATE TRIGGER trg_prediction_no_truncate BEFORE TRUNCATE ON prediction "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation();"
    )
    op.execute(
        "CREATE TRIGGER trg_release_risk_no_truncate BEFORE TRUNCATE ON release_risk "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_release_risk_no_truncate ON release_risk;")
    op.execute("DROP TRIGGER IF EXISTS trg_prediction_no_truncate ON prediction;")

    # Restore the previous (lexicographic) view definition from cb96ab2f3b5e.
    op.execute("DROP VIEW IF EXISTS abt_current;")
    op.execute(
        """
        CREATE VIEW abt_current AS
        SELECT DISTINCT ON (reservoir_id, date) *
        FROM analytical_base_table
        ORDER BY reservoir_id, date, abt_version DESC;
        """
    )
