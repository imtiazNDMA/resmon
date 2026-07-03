"""RS pipeline against the live DB: real Observations replace stubs, area tracks fill."""

from __future__ import annotations

from data_engineering.ingest import ingest_bulletins
from data_engineering.pipeline import DEFAULT_CSV
from data_engineering.seed import seed_reservoirs
from data_engineering.stub_observations import generate_stub_observations
from remote_sensing.pipeline import run_rs_pipeline
from sqlalchemy import text


def test_rs_emits_real_observations_replacing_stubs(session):
    seed_reservoirs(session)
    ingest_bulletins(session, DEFAULT_CSV)
    generate_stub_observations(session)  # stubs first (as DE would)

    summary = run_rs_pipeline(session, extractor_name="otsu_vh")
    assert summary["observations_written"] > 100
    assert summary["extraction_method"] == "otsu_vh"
    assert summary["mean_confidence"] > 0.5
    # clean synthetic scenes are always bimodal → the abstain gate never fires here
    assert summary["observations_skipped"] == 0

    conn = session.connection()
    n_real = conn.execute(
        text("SELECT count(*) FROM observation WHERE extraction_method = 'otsu_vh'")
    ).scalar_one()
    n_stub = conn.execute(
        text("SELECT count(*) FROM observation WHERE extraction_method = 'stub'")
    ).scalar_one()
    assert n_real > 0
    assert n_stub == 0  # real Observations replaced the stubs (same PK upsert)

    # Extracted area should track fill (the extractor recovers more water at higher fill).
    corr = conn.execute(
        text(
            """
            SELECT corr(o.surface_area, g.pct_filled)
            FROM observation o
            JOIN ground_truth g
              ON g.reservoir_id = o.reservoir_id AND g.date = o.acquisition_date
            WHERE o.extraction_method = 'otsu_vh' AND g.pct_filled IS NOT NULL
            """
        )
    ).scalar_one()
    assert corr is not None and corr > 0.9
