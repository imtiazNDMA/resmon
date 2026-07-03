"""Unit tests for forcing feature engineering (no DB): ERA5-Land unit conversions
(Kelvin → °C, metres → mm/day), NULL-not-zero propagation, and the publication-latency
shift applied at ABT join time."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from data_engineering.build_abt import _shift_to_available
from data_engineering.forcing import (
    ANTECEDENT_HALFLIFE_DAYS,
    ERA5_LAND_LAG_DAYS,
    MELT_FACTOR,
    engineer_forcing_features,
)


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2025-06-01", periods=n, freq="D")


def test_precip_metres_to_mm_per_day():
    idx = _idx(3)
    out = engineer_forcing_features(
        pd.Series([0.0, 0.012, 0.05], index=idx),  # ERA5-Land native metres/day
        pd.Series([273.15] * 3, index=idx),
    )
    assert out["catchment_precip"].tolist() == pytest.approx([0.0, 12.0, 50.0])


def test_temperature_kelvin_to_celsius_before_melt():
    idx = _idx(3)
    out = engineer_forcing_features(
        pd.Series([0.0] * 3, index=idx),
        pd.Series([263.15, 273.15, 300.15], index=idx),  # −10 °C, 0 °C, +27 °C
    )
    melt = out["degree_day_melt"]
    assert melt.iloc[0] == 0.0  # below base temperature → clipped
    assert melt.iloc[1] == 0.0  # exactly at base
    assert melt.iloc[2] == pytest.approx(27.0 * MELT_FACTOR)
    # Regression guard: raw Kelvin fed to the degree-day index would fabricate
    # ~(263..300) * 4 ≈ 1000+ mm/day of phantom melt on every row.
    assert (melt < 200).all()


def test_missing_inputs_stay_nan_not_zero():
    idx = _idx(3)
    out = engineer_forcing_features(
        pd.Series([0.001, np.nan, 0.002], index=idx),
        pd.Series([280.15, np.nan, 285.15], index=idx),
    )
    # Contract: NULL = not available — a coverage gap must never become a silent 0.0.
    assert np.isnan(out["catchment_precip"].iloc[1])
    assert np.isnan(out["degree_day_melt"].iloc[1])
    assert out["catchment_precip"].iloc[2] == pytest.approx(2.0)


def test_antecedent_index_decays_in_mm():
    idx = _idx(8)
    api = engineer_forcing_features(
        pd.Series([0.010] + [0.0] * 7, index=idx),  # 10 mm on day one, then dry
        pd.Series([273.15] * 8, index=idx),
    )["antecedent_precip_index"]
    assert api.iloc[0] == pytest.approx(10.0)  # mm, not metres
    # Exponentially-weighted with a 7-day halflife: half the mass gone after 7 dry days.
    assert api.iloc[ANTECEDENT_HALFLIFE_DAYS] == pytest.approx(5.0)
    assert (api.diff().dropna() < 0).all()


def test_forcing_shift_to_information_set_time():
    forcing = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-06-01", "2025-06-02"]),
            "catchment_precip": [1.0, 2.0],
        }
    )
    shifted = _shift_to_available(forcing)
    # Event date d becomes joinable only at d + lag (ERA5 publication latency).
    assert (shifted["date"] - forcing["date"]).dt.days.tolist() == [ERA5_LAND_LAG_DAYS] * 2
    assert shifted["catchment_precip"].tolist() == [1.0, 2.0]
    # The original frame is untouched (no in-place mutation surprises).
    assert forcing["date"].iloc[0] == pd.Timestamp("2025-06-01")
