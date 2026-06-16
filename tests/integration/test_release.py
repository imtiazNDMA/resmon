"""End-to-end release-risk against the live DB: persist ReleaseRisk + the AC-5 backtest."""

from __future__ import annotations

import pandas as pd
from data_engineering.ingest import ingest_bulletins
from data_engineering.pipeline import DEFAULT_CSV
from data_engineering.seed import seed_reservoirs
from ml.episodes import backtest_release_risk
from ml.forecasting import run_forecasting
from ml.release import run_release_risk
from ml.release_risk import RISK_LEVELS
from sqlalchemy import text


def test_release_risk_persists_per_reservoir(session):
    seed_reservoirs(session)
    ingest_bulletins(session, DEFAULT_CSV)
    run_forecasting(session, version="fc_rel")

    res = run_release_risk(session, abt_version="abt_v1")
    assert res["count"] == 3

    conn = session.connection()
    n = conn.execute(text("SELECT count(*) FROM release_risk")).scalar_one()
    assert n == 3
    levels = conn.execute(text("SELECT DISTINCT risk_level FROM release_risk")).scalars().all()
    assert all(lvl in RISK_LEVELS for lvl in levels)
    # Probabilities are in [0,1] (CHECK constraint also enforces this).
    bad = conn.execute(
        text(
            "SELECT count(*) FROM release_risk "
            "WHERE release_probability < 0 OR release_probability > 1"
        )
    ).scalar_one()
    assert bad == 0


def test_ac5_episode_backtest_fires_with_lead(session):
    seed_reservoirs(session)
    ingest_bulletins(session, DEFAULT_CSV)
    conn = session.connection()

    df = pd.read_sql(
        text(
            "SELECT reservoir_id, date, pct_filled FROM ground_truth "
            "WHERE pct_filled IS NOT NULL ORDER BY reservoir_id, date"
        ),
        conn,
        parse_dates=["date"],
    )
    thresholds = {
        rid: thr
        for rid, thr in conn.execute(
            text("SELECT reservoir_id, release_thresholds FROM reservoir")
        ).all()
    }

    results = backtest_release_risk(df, thresholds, near_frl_pct=95.0)
    assert len(results) > 0  # multiple near-FRL monsoon peaks across 11 years
    assert all(r["fired"] for r in results)
    mean_lead = sum(r["lead_time_days"] for r in results) / len(results)
    # AC-5: the transparent risk logic reaches Watch+ with usable lead before the peak.
    assert mean_lead >= 3.0
