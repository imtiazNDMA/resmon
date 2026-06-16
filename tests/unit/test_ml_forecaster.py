"""Unit tests for the pooled Δ-fill forecaster (no DB)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from ml.baselines import climatology_delta, mae, persistence_delta
from ml.forecaster import Forecaster, build_examples


def _recession_series() -> pd.DataFrame:
    dates = pd.date_range("2025-05-01", periods=30, freq="7D")
    pct = np.linspace(100.0, 40.0, 30)  # steady weekly recession
    return pd.DataFrame(
        {
            "reservoir_id": "r",
            "date": dates,
            "pct_filled": pct,
            "normal_storage_pct": pct,
            "live_capacity_bcm": 6.0,
        }
    )


def test_build_examples_delta_is_negative_in_recession():
    ex = build_examples(_recession_series())
    assert len(ex) > 0
    assert (ex["delta"] < 0).all()  # falling fill → negative Δ
    assert set(["current_pct", "horizon", "delta"]).issubset(ex.columns)


def test_model_beats_persistence_on_trend():
    ex = build_examples(_recession_series())
    n = len(ex)
    train, test = ex.iloc[: int(n * 0.7)], ex.iloc[int(n * 0.7) :]
    fc = Forecaster().fit(train)
    model_mae = mae(fc.predict_delta(test), test["delta"].to_numpy())
    persist_mae = mae(persistence_delta(len(test)), test["delta"].to_numpy())
    assert model_mae < persist_mae  # learning the trend beats predicting "no change"


def test_conformal_interval_brackets_prediction():
    ex = build_examples(_recession_series())
    fc = Forecaster().fit(ex)
    fc.conformalize(ex)
    pred, low, high = fc.predict_with_interval(ex)
    assert np.all(low <= pred) and np.all(pred <= high)


def test_climatology_delta_moves_toward_normal():
    d = climatology_delta(np.array([80.0]), np.array([60.0]))
    assert d[0] == -20.0
