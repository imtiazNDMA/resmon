"""End-to-end DE pipeline against the live DB: bulletins → ABT, with the AC-10
point-in-time leakage probe and the rerun-safety guard for real observations.
"""

from __future__ import annotations

import pandas as pd
import pytest
from data_engineering.pipeline import run_de_pipeline
from data_engineering.validation import validate_abt
from pipelines_common.dataaccess import FixtureBackend
from sqlalchemy import text


def test_de_pipeline_builds_abt_without_leakage(session):
    summary = run_de_pipeline(session, abt_version="abt_test", backend=FixtureBackend())

    assert summary["reservoirs_seeded"] == 3
    assert summary["upserted"] > 100  # ~583 bulletins across 3 reservoirs
    assert summary["stub_observations"] > 0
    # Stubs are excluded from ground-truth matching (they derive FROM the bulletins,
    # so matching would be circular) — with only stubs present, no matches exist.
    assert summary["ground_truth_matches"] == 0
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

    # ERA5 publication latency (information-set time): forcing for event date d is
    # joined at d + 5, so the ABT spine extends exactly 5 days past the last forcing row.
    abt_max = conn.execute(
        text("SELECT max(date) FROM analytical_base_table WHERE abt_version = 'abt_test'")
    ).scalar_one()
    forcing_max = conn.execute(text("SELECT max(date) FROM catchment_forcing")).scalar_one()
    assert (abt_max - forcing_max).days == 5

    # The gold ABT passes the validation schema (full snapshot — no sampling).
    df = pd.read_sql(
        text(
            "SELECT reservoir_id, date, frl, live_capacity_bcm, gt_pct_filled, "
            "surface_area, row_quality FROM analytical_base_table "
            "WHERE abt_version = 'abt_test'"
        ),
        conn,
    )
    validate_abt(df)


def test_de_pipeline_is_idempotent(session):
    first = run_de_pipeline(session, abt_version="abt_idem", backend=FixtureBackend())
    second = run_de_pipeline(session, abt_version="abt_idem", backend=FixtureBackend())
    # Same ABT row count on re-run (upserts, no duplicates).
    assert first["abt_rows"] == second["abt_rows"]


def test_de_rerun_does_not_clobber_real_observations(session):
    """A DE rerun must never overwrite a real SAR observation with a stub."""
    first = run_de_pipeline(session, abt_version="abt_guard", backend=FixtureBackend())
    conn = session.connection()

    # Promote one stub to a "real" SAR extraction (as the RS pipeline would).
    rid, adate = conn.execute(
        text(
            "SELECT reservoir_id, acquisition_date FROM observation "
            "ORDER BY reservoir_id, acquisition_date LIMIT 1"
        )
    ).one()
    conn.execute(
        text(
            "UPDATE observation SET extraction_method = 'otsu_vh', extraction_version = 'v1', "
            "surface_area = 123.456, area_confidence = 0.9 "
            "WHERE reservoir_id = :r AND acquisition_date = :d"
        ),
        {"r": rid, "d": adate},
    )

    second = run_de_pipeline(session, abt_version="abt_guard", backend=FixtureBackend())

    area, method = conn.execute(
        text(
            "SELECT surface_area, extraction_method FROM observation "
            "WHERE reservoir_id = :r AND acquisition_date = :d"
        ),
        {"r": rid, "d": adate},
    ).one()
    assert method == "otsu_vh"
    assert float(area) == pytest.approx(123.456)
    # Stub generation skips reservoirs that already carry real observations.
    assert second["stub_observations"] < first["stub_observations"]
    # With a real observation present, fusion now produces matches for it.
    assert second["ground_truth_matches"] > 0
