"""Unit tests for the release-risk layer + episode detection (no DB)."""

from __future__ import annotations

import numpy as np
import pandas as pd
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
        [1, 2, 3, 4, 5], [88, 92, 96, 97, 96], [90, 94, 98, 99, 98], THRESH, 80.0, 85.0
    )
    assert a.risk_level == "Warning"  # peak 97
    assert a.estimated_lead_time_days == 2  # first crosses watch (90) at horizon 2 (pct 92)
    assert a.release_probability > 0.5
    assert a.contributing_factors["band_crossed"] == "Warning"


def test_assess_low_forecast_is_low_no_lead():
    a = assess_release_risk([1, 2, 3], [50, 52, 51], [55, 57, 56], THRESH, 55.0, 50.0)
    assert a.risk_level == "Low"
    assert a.estimated_lead_time_days is None


def test_net_of_rule_curve_damps_routine_high_water():
    flood = assess_release_risk([1], [96], [97], THRESH, normal_pct=80.0, current_pct=90.0)
    routine = assess_release_risk([1], [96], [97], THRESH, normal_pct=99.0, current_pct=90.0)
    # Same band, but a peak below the seasonal normal is routine → damped probability.
    assert routine.release_probability < flood.release_probability


def test_detect_and_backtest_episode():
    dates = pd.date_range("2025-06-01", periods=12, freq="7D")
    pct = np.array([70, 80, 88, 93, 97, 99, 95, 90, 85, 80, 75, 70.0])  # rise to 99 then fall
    df = pd.DataFrame({"reservoir_id": "r", "date": dates, "pct_filled": pct})
    eps = detect_release_episodes(df, near_frl_pct=95.0)
    assert len(eps) == 1 and eps[0]["peak_pct"] == 99.0
    bt = backtest_release_risk(df, {"r": THRESH}, near_frl_pct=95.0)
    assert bt[0]["fired"] is True
    assert bt[0]["lead_time_days"] >= 7  # crossed watch (90) ≥ 1 week before the peak
