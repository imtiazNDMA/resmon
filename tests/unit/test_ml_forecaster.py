"""Unit tests for the pooled Δ-fill forecaster (no DB). Deterministic (seeded)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from ml.baselines import climatology_delta, mae, persistence_delta
from ml.forecaster import FORCING_FEATURES, Forecaster, build_examples, finite_sample_quantile


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


def _noisy_seasonal_series(n_weeks: int = 520, seed: int = 7, noise: float = 2.0) -> pd.DataFrame:
    """Weekly sinusoidal fill with known iid Gaussian noise — the conformal coverage
    target is checkable because the noise scale is known and exchangeable."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2015-01-05", periods=n_weeks, freq="7D")
    t = np.arange(n_weeks)
    seasonal = 60.0 + 25.0 * np.sin(2 * np.pi * t / 52.0)
    pct = np.clip(seasonal + rng.normal(0.0, noise, n_weeks), 0.0, 100.0)
    return pd.DataFrame(
        {
            "reservoir_id": "r",
            "date": dates,
            "pct_filled": pct,
            "normal_storage_pct": seasonal,
            "live_capacity_bcm": 6.0,
        }
    )


def test_build_examples_delta_is_negative_in_recession():
    ex = build_examples(_recession_series())
    assert len(ex) > 0
    assert (ex["delta"] < 0).all()  # falling fill → negative Δ
    assert set(["current_pct", "horizon", "delta"]).issubset(ex.columns)


def test_build_examples_carries_met_forcing_features():
    df = _recession_series().assign(
        catchment_precip=np.arange(30, dtype=float),
        antecedent_precip_index=10.0,
        snow_cover_area=0.2,
        swe=3.0,
        degree_day_melt=4.0,
        evaporation=1.0,
    )
    ex = build_examples(df)
    assert set(FORCING_FEATURES).issubset(ex.columns)
    first = ex.iloc[0]
    assert first["catchment_precip"] == 0.0
    assert first["degree_day_melt"] == 4.0


def test_model_beats_persistence_on_trend():
    ex = build_examples(_recession_series())
    n = len(ex)
    train, test = ex.iloc[: int(n * 0.7)], ex.iloc[int(n * 0.7) :]
    fc = Forecaster().fit(train)
    model_mae = mae(fc.predict_delta(test), test["delta"].to_numpy())
    persist_mae = mae(persistence_delta(len(test)), test["delta"].to_numpy())
    assert model_mae < persist_mae  # learning the trend beats predicting "no change"


def test_finite_sample_quantile_is_conservative():
    residuals = np.arange(1.0, 101.0)  # 1..100
    q = finite_sample_quantile(residuals, 0.9)
    # ceil((n+1)*0.9)/n with n=100 → the 0.91 order statistic ≥ the plain 0.9 quantile,
    # and it is an actual residual (method='higher').
    assert q >= float(np.quantile(residuals, 0.9))
    assert q in residuals
    # Tiny calibration sets fall back to the max residual.
    assert finite_sample_quantile(np.array([3.0, 1.0, 2.0]), 0.9) == 3.0
    with pytest.raises(ValueError, match="no calibration"):
        finite_sample_quantile(np.array([]), 0.9)


def test_conformal_interval_brackets_prediction():
    ex = build_examples(_recession_series())
    fc = Forecaster().fit(ex)
    fc.conformalize(ex)
    pred, low, high = fc.predict_with_interval(ex)
    assert np.all(low <= pred) and np.all(pred <= high)


def test_per_horizon_halfwidths_are_monotone():
    ex = build_examples(_noisy_seasonal_series())
    fc = Forecaster().fit(ex)
    fc.conformalize(ex)
    horizons = sorted(fc.conformal_halfwidths)
    assert horizons  # weekly series → at least the ~7/14-day horizons calibrated
    widths = [fc.conformal_halfwidths[h] for h in horizons]
    assert all(w > 0 for w in widths)
    assert widths == sorted(widths)  # uncertainty never shrinks with horizon


def test_trajectory_interpolates_between_trained_horizons():
    """C6: daily horizons are linear interpolation between (0, Δ=0) and the trained
    weekly anchors — never a raw tree query at an untrained horizon."""
    df = _recession_series()
    ex = build_examples(df)
    fc = Forecaster().fit(ex)
    fc.conformalize(ex)
    assert set(fc.trained_horizons) == {7, 14}  # weekly series → only 7/14-day gaps

    last = df.iloc[-1]
    prev = df.iloc[-2]
    current = float(last["pct_filled"])
    base = {
        "current_pct": current,
        "rate": (current - float(prev["pct_filled"])) / 7.0,
        "doy_sin": np.sin(2 * np.pi * last["date"].timetuple().tm_yday / 365.0),
        "doy_cos": np.cos(2 * np.pi * last["date"].timetuple().tm_yday / 365.0),
        "normal_pct": float(last["normal_storage_pct"]),
        "log_capacity": np.log(6.0),
    }
    horizons = list(range(1, 15))
    pred, low, high = fc.predict_fill_trajectory(base, horizons)

    # Anchor horizons match a direct model query.
    row7 = pd.DataFrame([{**base, "horizon": 7}])
    assert pred[6] == pytest.approx(current + fc.predict_delta(row7)[0], abs=1e-9)
    # Interpolated horizon 3 sits proportionally between Δ(0)=0 and Δ(7).
    delta7 = pred[6] - current
    assert pred[2] == pytest.approx(current + delta7 * 3.0 / 7.0, abs=1e-9)
    # Intervals bracket the point forecast and widen (weakly) with horizon.
    widths = high - low
    assert np.all(low <= pred) and np.all(pred <= high)
    assert np.all(np.diff(widths) >= -1e-12)


def test_picp_conformal_coverage_near_nominal():
    """C3: on synthetic data with known noise, the 90% split-conformal interval attains
    ~90% empirical coverage on a purged, held-out test period."""
    ex = build_examples(_noisy_seasonal_series(seed=7)).sort_values("base_date")
    dates = np.sort(ex["base_date"].unique())
    cal_start = dates[int(len(dates) * 0.6)]
    test_start = dates[int(len(dates) * 0.8)]
    fit_ex = ex[ex["target_date"] < cal_start]  # purge: nothing crosses the boundary
    cal_ex = ex[(ex["base_date"] >= cal_start) & (ex["target_date"] < test_start)]
    test_ex = ex[ex["base_date"] >= test_start]

    fc = Forecaster().fit(fit_ex)
    fc.conformalize(cal_ex)
    pred, low, high = fc.predict_with_interval(test_ex)
    actual = test_ex["current_pct"].to_numpy(dtype=float) + test_ex["delta"].to_numpy(dtype=float)
    picp = float(((actual >= low) & (actual <= high)).mean())
    assert picp == pytest.approx(0.9, abs=0.07)  # seeded → deterministic (≈0.918)


def test_climatology_delta_moves_toward_normal():
    d = climatology_delta(np.array([80.0]), np.array([60.0]))
    assert d[0] == -20.0
