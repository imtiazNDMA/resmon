"""Unit tests for the RS framework (no GEE, no DB)."""

from __future__ import annotations

import numpy as np
import pytest
from remote_sensing.aoi import aoi_bbox_from_occurrence, polygon_to_wkt
from remote_sensing.area import area_confidence, compactness, surface_area_km2
from remote_sensing.calibrate import db_to_linear, linear_to_db
from remote_sensing.extractors import available_extractors, get_extractor
from remote_sensing.harness import regime_mae, select_robust
from remote_sensing.pipeline import synth_scene


@pytest.mark.parametrize("name", ["otsu_vh", "kmeans", "gmm"])
def test_extractor_recovers_water_fraction(name):
    vv, vh, valid = synth_scene(40.0, seed=1)  # 40% water
    res = get_extractor(name).extract(vv, vh, valid, context={})
    frac = res.water_mask.mean()
    assert 0.30 < frac < 0.50  # recovers ~40%
    assert res.separability > 0.5  # clean bimodal → well separated


def test_registry_lists_cold_start_extractors():
    assert set(available_extractors()) == {"otsu_vh", "kmeans", "gmm"}
    with pytest.raises(ValueError, match="Unknown extractor"):
        get_extractor("nope")


def test_calibrate_db_linear_roundtrip():
    db = np.array([-22.0, -10.0, -5.0])
    assert np.allclose(linear_to_db(db_to_linear(db)), db)


def test_true_area_is_count_times_pixel_area():
    mask = np.zeros((10, 10), dtype=bool)
    mask[:5, :] = True  # 50 pixels
    assert surface_area_km2(mask, pixel_area_m2=1_000_000.0) == 50.0  # 50 km²


def test_confidence_monotonic():
    base = area_confidence(0.6, 0.8, 0.1)
    assert area_confidence(0.9, 0.8, 0.1) > base  # ↑separability ⇒ ↑confidence
    assert area_confidence(0.6, 0.8, 0.6) < base  # ↑layover ⇒ ↓confidence
    assert compactness(np.ones((8, 8), dtype=bool)) > compactness(
        np.eye(8, dtype=bool)  # solid block more compact than a diagonal
    )


def test_harness_selects_robust_not_lowest_mean():
    # 'steady' has a higher mean but never collapses; 'spiky' wins monsoon but dies on ice.
    metrics = {
        "steady": {"monsoon": 6.0, "winter_ice": 7.0},
        "spiky": {"monsoon": 2.0, "winter_ice": 20.0},
    }
    winner, worst = select_robust(metrics)
    assert winner == "steady"
    assert worst == 7.0


def test_regime_mae_groups_by_regime():
    areas = np.array([10.0, 20.0, 30.0, 40.0])
    pcts = np.array([10.0, 20.0, 30.0, 40.0])  # perfectly linear
    maes = regime_mae(areas, pcts, ["a", "a", "b", "b"])
    assert maes["a"] < 1e-6 and maes["b"] < 1e-6


def test_aoi_bbox_covers_water():
    occ = np.zeros((10, 10))
    occ[4:7, 3:6] = 80.0  # a water patch
    lons = np.linspace(76.0, 77.0, 10)
    lats = np.linspace(31.0, 32.0, 10)
    aoi = aoi_bbox_from_occurrence(occ, lons, lats, threshold_pct=50)
    assert aoi["type"] == "Polygon"
    assert polygon_to_wkt(aoi).startswith("MULTIPOLYGON")
