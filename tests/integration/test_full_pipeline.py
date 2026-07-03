"""AC-1 end-to-end chain: DE → RS → fusion → ABT → ML → serve in one pass (the
bootstrap path). The ABT is built after RS, so it must carry the run's real extractions."""

from __future__ import annotations

from orchestration.pipeline import run_full_pipeline
from sqlalchemy import text


def test_full_pipeline_runs_end_to_end(session):
    summary = run_full_pipeline(session)

    assert summary["de"]["reservoirs_seeded"] == 3
    assert summary["rs"]["observations_written"] > 100
    assert summary["abt_rows"] > 0
    assert summary["ground_truthing"]["ac2_passed"] is True
    assert summary["forecasting"]["predictions_written"] == 42
    assert summary["release_risk"]["count"] == 3

    conn = session.connection()
    # Every serving table the dashboard reads is populated.
    for table in ("ground_truth", "observation", "rating_curve", "prediction", "release_risk"):
        n = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
        assert n > 0, f"{table} empty after full pipeline"

    # A2: the ABT is built AFTER the RS stage, so it carries this run's real
    # extractions — never the bootstrap stubs.
    n_stub_abt = conn.execute(
        text("SELECT count(*) FROM analytical_base_table WHERE extraction_method = 'stub'")
    ).scalar_one()
    assert n_stub_abt == 0
    n_real_abt = conn.execute(
        text("SELECT count(*) FROM analytical_base_table WHERE extraction_method IS NOT NULL")
    ).scalar_one()
    assert n_real_abt > 100
    # ...and the SAR columns agree with the observation table row for the same date.
    mismatched = conn.execute(
        text(
            """
            SELECT count(*) FROM analytical_base_table a
            JOIN observation o
              ON o.reservoir_id = a.reservoir_id AND o.acquisition_date = a.date
            WHERE a.surface_area IS DISTINCT FROM o.surface_area
            """
        )
    ).scalar_one()
    assert mismatched == 0

    # A8: one pipeline_run row per stage, all successful.
    stage_rows = conn.execute(
        text("SELECT count(*) FROM pipeline_run WHERE status = 'success'")
    ).scalar_one()
    assert stage_rows == 7


def test_full_pipeline_is_rerunnable(session):
    run_full_pipeline(session)
    # Second pass must not raise (idempotent upserts incl. model_version ON CONFLICT).
    summary = run_full_pipeline(session)
    assert summary["release_risk"]["count"] == 3

    conn = session.connection()
    # Rerun converges: still no stub-derived rows in the rebuilt ABT.
    n_stub_abt = conn.execute(
        text("SELECT count(*) FROM analytical_base_table WHERE extraction_method = 'stub'")
    ).scalar_one()
    assert n_stub_abt == 0
    # Real observations exist everywhere, so the rerun generates no stubs at all.
    assert summary["de"]["stub_observations"] == 0
