"""End-to-end ground-truthing against the live DB: real Observations → matched pairs →
empirical rating curve → AC-2 gate + Pass-2 backfill.
"""

from __future__ import annotations

from data_engineering.fusion import fuse_observations_groundtruth
from data_engineering.ingest import ingest_bulletins
from data_engineering.pipeline import DEFAULT_CSV
from data_engineering.seed import seed_reservoirs
from ml.estimation import estimate_current
from ml.groundtruthing import run_ground_truthing
from remote_sensing.pipeline import run_rs_pipeline
from sqlalchemy import text


def test_ground_truthing_passes_ac2_and_backfills(session):
    seed_reservoirs(session)
    ingest_bulletins(session, DEFAULT_CSV)
    run_rs_pipeline(session, extractor_name="otsu_vh")  # real Observations
    fuse_observations_groundtruth(session)  # otsu matched pairs

    result = run_ground_truthing(session, version="rc_test", extraction_method="otsu_vh")

    assert result["curves_persisted"] == 3
    # Synthetic SAR → area tracks fill → the curve clears AC-2 comfortably (machinery check).
    assert result["ac2_passed"] is True
    assert result["ac2_worst_mae"] < 10.0
    # C5: the pass is stamped with its provenance — these observations are synthetic
    # (scene_ids=['synthetic'] from the RS pipeline), so AC-2 is a machinery pass.
    assert result["on_synthetic_data"] is True

    conn = session.connection()
    # Exactly one active curve per reservoir (partial-unique holds).
    n_active = conn.execute(text("SELECT count(*) FROM rating_curve WHERE is_active")).scalar_one()
    assert n_active == 3
    # The provenance flag is persisted into every curve's fit_metrics JSON (C5).
    n_flagged = conn.execute(
        text(
            "SELECT count(*) FROM rating_curve "
            "WHERE is_active AND fit_metrics->>'on_synthetic_data' = 'true'"
        )
    ).scalar_one()
    assert n_flagged == 3
    metrics = conn.execute(
        text(
            "SELECT fit_metrics FROM rating_curve WHERE reservoir_id = 'gobind_sagar' AND is_active"
        )
    ).scalar_one()
    assert metrics["n_pairs"] >= 5
    assert 0.0 <= metrics["area_storage_pearson_r"] <= 1.0
    assert 0.0 <= metrics["area_level_pearson_r"] <= 1.0

    # Pass-2 backfill landed on both the match table and observations.
    n_match_derived = conn.execute(
        text("SELECT count(*) FROM ground_truth_match WHERE derived_pct_filled IS NOT NULL")
    ).scalar_one()
    assert n_match_derived > 100
    n_obs_derived = conn.execute(
        text("SELECT count(*) FROM observation WHERE derived_volume IS NOT NULL")
    ).scalar_one()
    assert n_obs_derived > 100


def test_ground_truthing_gate_fails_on_tight_tolerance(session):
    seed_reservoirs(session)
    ingest_bulletins(session, DEFAULT_CSV)
    run_rs_pipeline(session, extractor_name="otsu_vh")
    fuse_observations_groundtruth(session)
    # An absurdly tight tolerance must fail the gate even on synthetic data.
    result = run_ground_truthing(
        session, version="rc_tight", extraction_method="otsu_vh", tolerance=0.0001
    )
    assert result["ac2_passed"] is False


def test_estimation_bridge_maps_latest_area(session):
    seed_reservoirs(session)
    ingest_bulletins(session, DEFAULT_CSV)
    run_rs_pipeline(session, extractor_name="otsu_vh")
    fuse_observations_groundtruth(session)
    run_ground_truthing(session, version="rc_est", extraction_method="otsu_vh")

    est = estimate_current(session)
    assert len(est) == 3
    for e in est.values():
        assert e["storage_bcm"] > 0
        assert e["pct_filled"] >= 0
        assert e["rating_curve_version"] == "rc_est"
