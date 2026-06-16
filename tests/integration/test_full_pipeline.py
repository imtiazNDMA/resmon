"""AC-1 end-to-end chain: RS → DE → ML → serve in one pass (the bootstrap path)."""

from __future__ import annotations

from orchestration.pipeline import run_full_pipeline
from sqlalchemy import text


def test_full_pipeline_runs_end_to_end(session):
    summary = run_full_pipeline(session)

    assert summary["de"]["reservoirs_seeded"] == 3
    assert summary["rs"]["observations_written"] > 100
    assert summary["ground_truthing"]["ac2_passed"] is True
    assert summary["forecasting"]["predictions_written"] == 42
    assert summary["release_risk"]["count"] == 3

    conn = session.connection()
    # Every serving table the dashboard reads is populated.
    for table in ("ground_truth", "observation", "rating_curve", "prediction", "release_risk"):
        n = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
        assert n > 0, f"{table} empty after full pipeline"


def test_full_pipeline_is_rerunnable(session):
    run_full_pipeline(session)
    # Second pass must not raise (idempotent upserts incl. model_version ON CONFLICT).
    summary = run_full_pipeline(session)
    assert summary["release_risk"]["count"] == 3
