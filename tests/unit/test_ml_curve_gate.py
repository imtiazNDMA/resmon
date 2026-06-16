"""Unit tests for the empirical rating curve + AC-2 gate (no DB)."""

from __future__ import annotations

import numpy as np
import pytest
from ml.curve import fit_empirical
from ml.gate import ac2_gate, fill_pct_mae


def test_curve_fit_recovers_linear():
    areas = np.array([10.0, 20.0, 30.0, 40.0])
    storage = np.array([1.0, 2.0, 3.0, 4.0])  # storage = area / 10
    level = np.array([400.0, 410.0, 420.0, 430.0])
    fit = fit_empirical("r", "v1", areas, storage, level, capacity_bcm=6.0)
    assert fit.storage_for_area(25.0) == pytest.approx(2.5, abs=1e-6)
    assert fit.level_for_area(10.0) == pytest.approx(400.0, abs=1e-6)
    # storage at area 60 = 6.0 BCM = 100% of capacity.
    assert fit.pct_filled_for_area(60.0) == pytest.approx(100.0, abs=1e-6)
    assert fit.is_extrapolated(50.0) is True  # above observed area_max=40
    assert fit.is_extrapolated(35.0) is False


def test_curve_needs_enough_pairs():
    with pytest.raises(ValueError, match="need"):
        fit_empirical("r", "v", np.array([1.0]), np.array([1.0]), np.array([1.0]), 6.0)


def test_ac2_gate_pass_and_fail():
    ok = ac2_gate({"a": 5.0, "b": 9.0}, tolerance=10.0)
    assert ok.passed and ok.worst_mae == 9.0
    bad = ac2_gate({"a": 5.0, "b": 12.0}, tolerance=10.0)
    assert not bad.passed and bad.worst_reservoir == "b"
    assert not ac2_gate({}, tolerance=10.0).passed


def test_fill_pct_mae():
    assert fill_pct_mae(np.array([10.0, 20.0]), np.array([12.0, 18.0])) == pytest.approx(2.0)
