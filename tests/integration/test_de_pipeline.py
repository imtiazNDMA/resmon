"""End-to-end DE pipeline against the live DB: bulletins → ABT, with the AC-10
point-in-time leakage probe.
"""

from __future__ import annotations

import pandas as pd
from data_engineering.pipeline import run_de_pipeline
from data_engineering.validation import validate_abt
from pipelines_common.dataaccess import FixtureBackend
from sqlalchemy import text


def test_de_pipeline_builds_abt_without_leakage(session):
    summary = run_de_pipeline(session, abt_version="abt_test", backend=FixtureBackend())

    assert summary["reservoirs_seeded"] == 3
    assert summary["upserted"] > 100  # ~583 bulletins across 3 reservoirs
    assert summary["stub_observations"] > 0
    assert summary["ground_truth_matches"] > 0
    assert summary["abt_rows"] > 0

    conn = session.connection()

    # Leakage probe (AC-10): a populated gt_pct_filled must sit on a real bulletin date —
    # never smeared onto an earlier row by a forward/asof join.
    leaked = conn.execute(
        text(
            """
            SELECT count(*) FROM analytical_base_table a
            WHERE a.abt_version = 'abt_test' AND a.gt_pct_filled IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM ground_truth g
                WHERE g.reservoir_id = a.reservoir_id AND g.date = a.date
              )
            """
        )
    ).scalar_one()
    assert leaked == 0

    # Recency is always backward (non-negative).
    bad_recency = conn.execute(
        text(
            "SELECT count(*) FROM analytical_base_table "
            "WHERE abt_version = 'abt_test' AND days_since_bulletin < 0"
        )
    ).scalar_one()
    assert bad_recency == 0

    # The gold ABT passes the validation schema.
    df = pd.read_sql(
        text(
            "SELECT reservoir_id, date, frl, live_capacity_bcm, gt_pct_filled, "
            "surface_area, row_quality FROM analytical_base_table "
            "WHERE abt_version = 'abt_test' LIMIT 500"
        ),
        conn,
    )
    validate_abt(df)


def test_de_pipeline_is_idempotent(session):
    first = run_de_pipeline(session, abt_version="abt_idem", backend=FixtureBackend())
    second = run_de_pipeline(session, abt_version="abt_idem", backend=FixtureBackend())
    # Same ABT row count on re-run (upserts, no duplicates).
    assert first["abt_rows"] == second["abt_rows"]
