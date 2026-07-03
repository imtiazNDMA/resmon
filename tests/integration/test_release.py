"""End-to-end release-risk against the live DB: persist ReleaseRisk + the AC-5
replayed backtest (episodes scored against a hindsight-free forecaster replay)."""

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


def test_ac5_replayed_backtest_scores_observed_episodes(session):
    """AC-5 (ADR-0001): replay the forecaster + risk logic through the held-out years
    and score against observed near-FRL episodes. The old test asserted fired==True on
    hindsight-derived episodes — a tautology. This one asserts the replayed metrics."""
    seed_reservoirs(session)
    ingest_bulletins(session, DEFAULT_CSV)
    conn = session.connection()

    df = pd.read_sql(
        text(
            "SELECT reservoir_id, date, pct_filled, normal_storage_pct, live_capacity_bcm "
            "FROM ground_truth WHERE pct_filled IS NOT NULL ORDER BY reservoir_id, date"
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

    report = backtest_release_risk(df, thresholds, near_frl_pct=95.0)

    assert report["evaluated"] is True
    assert report["n_assessments"] > 0  # weekly replay across the held-out years
    # The 11-year record has post-cutoff near-FRL monsoon peaks (2023/2025) to score.
    assert report["n_episodes"] >= 1
    assert report["hits"] + report["misses"] == report["n_episodes"]
    assert report["false_alarms"] >= 0 and report["unresolved_alerts"] >= 0

    for ep in report["episodes"]:
        assert "fired" not in ep  # no hard-coded outcome — hits are earned, not asserted
        if ep["hit"]:
            assert ep["lead_time_days"] is not None and ep["lead_time_days"] >= 0
        else:
            assert ep["lead_time_days"] is None
    if report["hits"]:
        assert report["mean_lead_days"] is not None and report["mean_lead_days"] >= 0

    for a in report["assessments"]:
        assert a["risk_level"] in RISK_LEVELS
        assert 0.0 <= a["release_probability"] <= 1.0

    # NOTE: we deliberately do NOT assert mean lead ≥ 3 days (the AC-5 skill target).
    # Without real inflow forcing the Δ-fill model adds little beyond current state
    # (e.g. the Aug-2023 Pong flood filled 75→100% inside one bulletin week — an honest
    # miss for any storage-only model). The skill claim awaits real forcing data; this
    # test verifies the replayed-backtest machinery and metric semantics.
