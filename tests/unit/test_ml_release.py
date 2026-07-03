"""Unit tests for the release-risk layer + episode detection/replayed backtest (no DB).

All deterministic — synthetic series are constructed, not sampled.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from ml.episodes import backtest_release_risk, detect_release_episodes
from ml.release_risk import RISK_LEVELS, assess_release_risk, risk_band

THRESH = {"watch": {"pct": 90}, "warning": {"pct": 95}, "imminent": {"pct": 98}}


def test_risk_band_maps_fill_to_level():
    assert risk_band(99, THRESH) == "Imminent"
    assert risk_band(96, THRESH) == "Warning"
    assert risk_band(91, THRESH) == "Watch"
    assert risk_band(50, THRESH) == "Low"
    assert all(b in RISK_LEVELS for b in ("Low", "Watch", "Warning", "Imminent"))


def test_assess_high_forecast_is_warning_with_lead():
    a = assess_release_risk(
        [1, 2, 3, 4, 5],
        [88, 92, 96, 97, 96],
        [86, 90, 94, 95, 94],
        [90, 94, 98, 99, 98],
        THRESH,
        80.0,
        85.0,
    )
    assert a.risk_level == "Warning"  # peak 97
    assert a.estimated_lead_time_days == 2  # first crosses watch (90) at horizon 2 (pct 92)
    # Peak-horizon interval [95, 99] sits entirely at/above warning (95) → index 1.0.
    assert a.release_probability > 0.5
    assert a.contributing_factors["band_crossed"] == "Warning"
    assert a.contributing_factors["forecast_peak_horizon_days"] == 4


def test_assess_low_forecast_is_low_no_lead():
    a = assess_release_risk([1, 2, 3], [50, 52, 51], [45, 47, 46], [55, 57, 56], THRESH, 55.0, 50.0)
    assert a.risk_level == "Low"
    assert a.estimated_lead_time_days is None
    assert a.release_probability <= 0.5  # consistency: no lead → index capped


def test_missing_interval_is_not_zero_uncertainty():
    """C7: a NULL interval must widen, not vanish — the index still reflects that the
    warning line may fall inside the (fallback) uncertainty band."""
    a = assess_release_risk([1], [94.0], [None], [None], THRESH, 80.0, 90.0)
    # Fallback halfwidth 5 → interval [89, 99]; fraction above warning (95) = 0.4.
    assert a.release_probability == pytest.approx(0.4)
    # Zero-uncertainty behaviour (point 94 < warning 95) would have produced 0.
    assert a.release_probability > 0.0


def test_index_above_half_implies_lead():
    """C2 consistency: index > 0.5 must imply a non-None lead, even for a wildly
    asymmetric interval whose upper bound clears warning."""
    a = assess_release_risk([1], [85.0], [84.0], [200.0], THRESH, 60.0, 80.0)
    assert a.estimated_lead_time_days is None
    assert a.release_probability <= 0.5


def test_net_of_rule_curve_damps_routine_high_water():
    flood = assess_release_risk([1], [96], [95], [97], THRESH, normal_pct=80.0, current_pct=90.0)
    routine = assess_release_risk([1], [96], [95], [97], THRESH, normal_pct=99.0, current_pct=90.0)
    # Same band, but a peak below the seasonal normal is routine → damped index.
    assert routine.release_probability < flood.release_probability


def test_detect_episode_with_onset():
    dates = pd.date_range("2025-06-01", periods=12, freq="7D")
    pct = np.array([70, 80, 88, 93, 97, 99, 95, 90, 85, 80, 75, 70.0])  # rise to 99 then fall
    df = pd.DataFrame({"reservoir_id": "r", "date": dates, "pct_filled": pct})
    eps = detect_release_episodes(df, near_frl_pct=95.0)
    assert len(eps) == 1 and eps[0]["peak_pct"] == 99.0
    assert eps[0]["peak_date"] == dates[5]
    assert eps[0]["onset_date"] == dates[4]  # first date of the contiguous ≥95 run


def test_detect_handles_sustained_plateau():
    """C8: a sustained 100% fill is one episode, dated at the plateau's first index."""
    dates = pd.date_range("2025-06-01", periods=8, freq="7D")
    pct = np.array([70, 90, 96, 100, 100, 100, 92, 80.0])
    df = pd.DataFrame({"reservoir_id": "r", "date": dates, "pct_filled": pct})
    eps = detect_release_episodes(df, near_frl_pct=95.0)
    assert len(eps) == 1
    assert eps[0]["peak_pct"] == 100.0
    assert eps[0]["peak_date"] == dates[3]  # first index of the maximal run
    assert eps[0]["onset_date"] == dates[2]  # 96 is the first ≥95 value


def test_detect_uses_per_reservoir_thresholds():
    """C8: the near-FRL line comes from the reservoir's warning band when provided."""
    dates = pd.date_range("2025-06-01", periods=6, freq="7D")
    pct = np.array([70, 80, 88, 86, 75, 70.0])  # peaks at 88
    df = pd.DataFrame({"reservoir_id": "r", "date": dates, "pct_filled": pct})
    assert detect_release_episodes(df, near_frl_pct=95.0) == []
    low_thresholds = {"r": {"watch": {"pct": 80}, "warning": {"pct": 85}, "imminent": {"pct": 95}}}
    eps = detect_release_episodes(df, near_frl_pct=95.0, thresholds_by_reservoir=low_thresholds)
    assert len(eps) == 1 and eps[0]["peak_pct"] == 88.0


def _triangle_series(n_years: int = 6) -> pd.DataFrame:
    """Deterministic seasonal triangle: each year rises 40→97 over 26 weeks, then falls
    back. Every peak crosses watch (90) gradually, ~2 weeks before near-FRL (95)."""
    weeks: list[float] = []
    for _ in range(n_years):
        rise = np.linspace(40.0, 97.0, 26)
        fall = np.linspace(97.0, 40.0, 27)[1:]
        weeks.extend(rise.tolist() + fall.tolist())
    pct = np.array(weeks)
    dates = pd.date_range("2015-01-05", periods=len(pct), freq="7D")
    return pd.DataFrame(
        {
            "reservoir_id": "r",
            "date": dates,
            "pct_filled": pct,
            "normal_storage_pct": pct - 10.0,  # peaks sit above the seasonal normal
            "live_capacity_bcm": 6.0,
        }
    )


def test_backtest_replays_forecaster_and_scores_episodes():
    """C1: the backtest must replay a forecaster trained strictly before the cutoff and
    score against subsequently observed episodes — nothing is fired by construction."""
    df = _triangle_series()
    bt = backtest_release_risk(df, {"r": THRESH}, near_frl_pct=95.0)

    assert bt["evaluated"] is True
    # Two post-cutoff annual peaks fall in the replay period (train_frac=0.6 of 6y).
    assert bt["n_episodes"] == 2
    assert bt["hits"] + bt["misses"] == bt["n_episodes"]
    assert bt["false_alarms"] >= 0 and bt["unresolved_alerts"] >= 0
    assert bt["n_assessments"] > 50  # weekly replay over the held-out years

    for ep in bt["episodes"]:
        assert "fired" not in ep  # the old tautology is gone
        assert ep["hit"] in (True, False)
        if ep["hit"]:
            assert ep["lead_time_days"] is not None and ep["lead_time_days"] >= 0
        else:
            assert ep["lead_time_days"] is None
    # On this smooth deterministic approach the replayed logic warns ahead of onset.
    assert bt["hits"] == 2
    assert bt["mean_lead_days"] is not None and bt["mean_lead_days"] >= 7.0

    for a in bt["assessments"]:
        assert a["risk_level"] in RISK_LEVELS
        assert 0.0 <= a["release_probability"] <= 1.0


def test_backtest_refuses_insufficient_history():
    dates = pd.date_range("2025-06-01", periods=12, freq="7D")
    pct = np.array([70, 80, 88, 93, 97, 99, 95, 90, 85, 80, 75, 70.0])
    df = pd.DataFrame(
        {
            "reservoir_id": "r",
            "date": dates,
            "pct_filled": pct,
            "normal_storage_pct": pct - 5.0,
            "live_capacity_bcm": 6.0,
        }
    )
    bt = backtest_release_risk(df, {"r": THRESH})
    assert bt["evaluated"] is False
