"""Unit tests for the RS framework (no GEE, no DB).

Adversarial extractor cases use gamma-distributed speckle (ENL ≈ 4.5, S1 GRD native) in
linear power converted to dB — not trivial 1 dB Gaussian noise. Multilooked variants use
a 3×3 boxcar in the linear domain, mirroring the focal-median speckle reduction the
production GEE path applies before thresholding.
"""

from __future__ import annotations

import numpy as np
import pytest
from remote_sensing.aoi import (
    analysis_exclusion_geojson,
    aoi_bbox_from_occurrence,
    dam_connected_component,
    polygon_to_wkt,
)
from remote_sensing.area import area_confidence, compactness, polygon_compactness, surface_area_km2
from remote_sensing.calibrate import db_to_linear, linear_to_db, mask_border_noise
from remote_sensing.extractors import (
    OtsuVH,
    available_extractors,
    fisher_from_histogram,
    fisher_separability,
    get_extractor,
    otsu_from_histogram,
    valley_ratio,
)
from remote_sensing.gee_real import GeeExtractionError, _upstream_basin_ids
from remote_sensing.harness import regime_mae, select_robust
from remote_sensing.pipeline import synth_scene
from scipy.ndimage import uniform_filter

ALL_EXTRACTORS = ["otsu_vh", "kmeans", "gmm"]
GRID = 64
ENL = 4.5  # native S1 GRD equivalent number of looks


def speckle_scene(
    water_frac: float,
    *,
    vh_water_db: float,
    vh_land_db: float,
    vv_offset_db: float = 5.0,
    enl: float = ENL,
    multilook: bool = False,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(vv, vh, valid, true_water): gamma speckle in linear power → dB. ``multilook``
    applies a 3×3 boxcar in the linear domain (as production smoothing does)."""
    rng = np.random.default_rng(seed)
    water = np.zeros((GRID, GRID), dtype=bool)
    water[: int(round(water_frac * GRID)), :] = True

    def band(mean_water_db: float, mean_land_db: float) -> np.ndarray:
        mean_lin = np.where(water, db_to_linear(mean_water_db), db_to_linear(mean_land_db))
        lin = rng.gamma(enl, mean_lin / enl)
        if multilook:
            lin = uniform_filter(lin, size=3, mode="nearest")
        return linear_to_db(lin)

    vh = band(vh_water_db, vh_land_db)
    vv = band(vh_water_db + vv_offset_db, vh_land_db + vv_offset_db)
    return vv, vh, np.ones((GRID, GRID), dtype=bool), water


# ---------------------------------------------------------------- basic recovery


@pytest.mark.parametrize("name", ALL_EXTRACTORS)
def test_extractor_recovers_water_fraction(name):
    vv, vh, valid = synth_scene(40.0, seed=1)  # 40% water, clean 12 dB separation
    res = get_extractor(name).extract(vv, vh, valid, context={})
    assert not res.abstained
    frac = res.water_mask.mean()
    assert 0.30 < frac < 0.50  # recovers ~40%
    assert res.separability > 0.5  # clean bimodal → well separated (unified Fisher)


def test_registry_lists_cold_start_extractors():
    assert set(available_extractors()) == {"otsu_vh", "kmeans", "gmm"}
    with pytest.raises(ValueError, match="Unknown extractor"):
        get_extractor("nope")


# ---------------------------------------------------------------- adversarial scenes


@pytest.mark.parametrize("name", ALL_EXTRACTORS)
def test_speckled_5db_separation_still_extracts(name):
    """Gamma speckle (ENL≈4.5) + only 5 dB mode separation, multilooked as in prod."""
    vv, vh, valid, water = speckle_scene(
        0.4, vh_water_db=-22.0, vh_land_db=-17.0, multilook=True, seed=7
    )
    res = get_extractor(name).extract(vv, vh, valid, context={})
    assert not res.abstained
    assert 0.28 < res.water_mask.mean() < 0.52
    assert res.separability > 0.5
    # the mask should actually be the water, not an arbitrary partition
    assert res.water_mask[water].mean() > 0.8
    assert res.water_mask[~water].mean() < 0.1


@pytest.mark.parametrize("name", ALL_EXTRACTORS)
def test_wind_merged_modes_abstain_or_low_separability(name):
    """Wind-roughened water: VH modes ~1.5 dB apart under raw ENL 4.5 speckle merge into
    one histogram mode — no confident mask may be produced."""
    vv, vh, valid, _ = speckle_scene(0.4, vh_water_db=-13.5, vh_land_db=-12.0, seed=11)
    res = get_extractor(name).extract(vv, vh, valid, context={})
    assert res.abstained or res.separability < 0.3
    if res.abstained:
        assert not res.water_mask.any()


@pytest.mark.parametrize("name", ALL_EXTRACTORS)
def test_dry_pool_unimodal_must_abstain(name):
    """A dry pool is land-only speckle: unimodal → the extractor MUST abstain, never
    'find' water in a partition artefact."""
    vv, vh, valid, _ = speckle_scene(0.0, vh_water_db=-22.0, vh_land_db=-12.0, seed=3)
    res = get_extractor(name).extract(vv, vh, valid, context={})
    assert res.abstained
    assert not res.water_mask.any()
    assert res.separability == 0.0
    assert "abstain_reason" in res.diagnostics


@pytest.mark.parametrize("name", ALL_EXTRACTORS)
def test_small_water_fraction_detected(name):
    """<5 % water (a nearly drawn-down pool) with clear contrast must still be found."""
    vv, vh, valid, water = speckle_scene(
        3 / GRID, vh_water_db=-22.0, vh_land_db=-12.0, multilook=True, seed=5
    )
    res = get_extractor(name).extract(vv, vh, valid, context={})
    assert not res.abstained
    assert 0.005 < res.water_mask.mean() < 0.08
    assert res.water_mask[water].mean() > 0.3  # finds the pool
    assert res.water_mask[~water].mean() < 0.02  # without flooding the land


@pytest.mark.parametrize("name", ALL_EXTRACTORS)
def test_nan_borders_are_ignored(name):
    """NaN borders (scene edges / masked pixels) must be excluded from histogram +
    clustering inputs and can never be classified as water."""
    vv, vh, valid = synth_scene(40.0, seed=2)
    vh[:2, :] = np.nan
    vh[:, -2:] = np.nan
    vv[:2, :] = np.nan
    vv[:, -2:] = np.nan
    res = get_extractor(name).extract(vv, vh, valid, context={})
    assert not res.abstained
    assert not res.water_mask[:2, :].any()
    assert not res.water_mask[:, -2:].any()
    assert 0.25 < res.water_mask.mean() < 0.50
    assert np.isfinite(res.separability)


@pytest.mark.parametrize("name", ALL_EXTRACTORS)
def test_too_few_valid_pixels_abstains(name):
    vv, vh, valid = synth_scene(40.0, seed=4)
    valid[:] = False
    valid[0, :8] = True  # 8 valid pixels only
    res = get_extractor(name).extract(vv, vh, valid, context={})
    assert res.abstained


# ---------------------------------------------------------------- shared Otsu + gates


def test_otsu_histogram_and_array_paths_share_one_implementation():
    """The GEE path runs Otsu on (counts, bucketMeans) pulled from the server; it must
    give the same threshold the array extractor derives from the same data."""
    _, vh, valid = synth_scene(40.0, seed=9)
    res = OtsuVH().extract(vh + 5.0, vh, valid, context={})
    counts, edges = np.histogram(vh[valid], bins=256)
    centers = (edges[:-1] + edges[1:]) / 2
    # GEE returns plain lists — the shared implementation must accept them as-is
    threshold, eta = otsu_from_histogram(list(counts), list(centers))
    assert res.threshold_used == pytest.approx(threshold)
    assert -22.0 < threshold < -10.0  # cut lies between the water and land modes
    assert 0.0 < eta <= 1.0


def test_otsu_from_histogram_rejects_empty():
    with pytest.raises(ValueError):
        otsu_from_histogram([], [])
    with pytest.raises(ValueError):
        otsu_from_histogram([0, 0, 0], [1.0, 2.0, 3.0])


def test_valley_ratio_separates_bimodal_from_unimodal():
    centers = np.linspace(-30.0, 0.0, 256)
    bimodal = np.exp(-0.5 * ((centers + 22) / 1.0) ** 2) + np.exp(
        -0.5 * ((centers + 10) / 1.0) ** 2
    )
    unimodal = np.exp(-0.5 * ((centers + 15) / 2.0) ** 2)
    assert valley_ratio(bimodal, centers, -16.0) < 0.2
    assert valley_ratio(unimodal, centers, -15.0) > 0.8


def test_fisher_from_histogram_matches_sample_fisher():
    rng = np.random.default_rng(0)
    a = rng.normal(-22.0, 1.0, 4000)
    b = rng.normal(-10.0, 1.0, 6000)
    vals = np.concatenate([a, b])
    counts, edges = np.histogram(vals, bins=512)
    centers = (edges[:-1] + edges[1:]) / 2
    hist_f = fisher_from_histogram(counts, centers, -16.0)
    sample_f = fisher_separability(vals[vals < -16.0], vals[vals >= -16.0])
    assert hist_f == pytest.approx(sample_f, abs=0.02)
    assert hist_f > 0.9


# ---------------------------------------------------------------- catchment traversal


def _basin(hybas_id: int, next_down: int) -> dict:
    return {"HYBAS_ID": hybas_id, "NEXT_DOWN": next_down}


def test_upstream_traversal_collects_all_upstream_basins():
    #   4   5
    #    \ /
    # 6   2    (7 is downstream of the seed; 8/9 a separate river)
    #  \ /
    #   1 -> 7 -> 0        8 -> 9 -> 0
    basins = [
        _basin(1, 7),
        _basin(2, 1),
        _basin(4, 2),
        _basin(5, 2),
        _basin(6, 1),
        _basin(7, 0),
        _basin(8, 9),
        _basin(9, 0),
    ]
    assert _upstream_basin_ids(basins, 1) == {1, 2, 4, 5, 6}
    assert _upstream_basin_ids(basins, 2) == {2, 4, 5}
    assert _upstream_basin_ids(basins, 7) == {7, 1, 2, 4, 5, 6}  # everything drains in


def test_upstream_traversal_is_cycle_safe_and_bounded():
    cyclic = [_basin(1, 2), _basin(2, 1), _basin(3, 1)]
    assert _upstream_basin_ids(cyclic, 1) == {1, 2, 3}  # terminates despite the cycle
    chain = [_basin(i + 1, i) for i in range(50)]
    with pytest.raises(GeeExtractionError, match="exceeded"):
        _upstream_basin_ids(chain, 0, max_basins=10)


# ---------------------------------------------------------------- calibration / area


def test_calibrate_db_linear_roundtrip():
    db = np.array([-22.0, -10.0, -5.0])
    assert np.allclose(linear_to_db(db_to_linear(db)), db)


def test_mask_border_noise_drops_extreme_low_db():
    db = np.array([[-35.0, -22.0], [-12.0, -31.0]])
    assert mask_border_noise(db).tolist() == [[False, True], [True, False]]


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


def test_polygon_compactness_square_beats_sliver():
    square = {
        "type": "Polygon",
        "coordinates": [[[76.0, 31.0], [76.1, 31.0], [76.1, 31.1], [76.0, 31.1], [76.0, 31.0]]],
    }
    sliver = {
        "type": "Polygon",
        "coordinates": [[[76.0, 31.0], [76.5, 31.0], [76.5, 31.001], [76.0, 31.001], [76.0, 31.0]]],
    }
    cs, cl = polygon_compactness(square), polygon_compactness(sliver)
    assert 0.0 < cl < cs <= 1.0
    assert polygon_compactness({"type": "Polygon", "coordinates": []}) == 0.0


def test_thein_area_excludes_downstream_river_only():
    exclusion = analysis_exclusion_geojson("thein")
    assert exclusion is not None
    assert analysis_exclusion_geojson("gobind_sagar") is None
    assert exclusion["type"] == "Polygon"
    assert exclusion["coordinates"][0][0] == [75.7303, 32.4431]


# ---------------------------------------------------------------- harness


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


# ---------------------------------------------------------------- AOI


def test_aoi_bbox_covers_water():
    occ = np.zeros((10, 10))
    occ[4:7, 3:6] = 80.0  # a water patch
    lons = np.linspace(76.0, 77.0, 10)
    lats = np.linspace(31.0, 32.0, 10)
    aoi = aoi_bbox_from_occurrence(occ, lons, lats, threshold_pct=50)
    assert aoi["type"] == "Polygon"
    assert polygon_to_wkt(aoi).startswith("MULTIPOLYGON")


def test_aoi_uses_dam_connected_component_not_all_pixels():
    occ = np.zeros((20, 20))
    occ[2:6, 2:6] = 10.0  # reservoir near the dam
    occ[14:18, 14:18] = 90.0  # unrelated water body far away
    lons = np.linspace(76.0, 77.0, 20)
    lats = np.linspace(31.0, 32.0, 20)
    dam_lon, dam_lat = lons[2], lats[3]  # on the reservoir patch
    aoi = aoi_bbox_from_occurrence(occ, lons, lats, dam_lon=dam_lon, dam_lat=dam_lat)
    assert aoi["properties"]["selection"] == "dam_connected_component"
    ring = np.array(aoi["coordinates"][0])
    # bbox stays around the dam-connected patch; the far water body is excluded
    assert ring[:, 0].max() < lons[10]
    assert ring[:, 1].max() < lats[10]
    # default threshold keeps the rarely-inundated margin (occurrence 10 % ≥ 5 %)
    assert aoi["properties"]["occurrence_threshold_pct"] == 5.0


def test_dam_connected_component_flood_fill():
    water = np.zeros((8, 8), dtype=bool)
    water[1:3, 1:3] = True
    water[6, 6] = True  # disconnected pixel
    comp = dam_connected_component(water, (1, 1))
    assert comp.sum() == 4 and not comp[6, 6]
    with pytest.raises(ValueError, match="not water"):
        dam_connected_component(water, (0, 0))


def test_aoi_snaps_dam_point_to_nearby_water_only():
    occ = np.zeros((20, 20))
    occ[8:12, 8:12] = 50.0
    lons = np.linspace(76.0, 77.0, 20)
    lats = np.linspace(31.0, 32.0, 20)
    # dam one pixel off the pool → snaps
    aoi = aoi_bbox_from_occurrence(occ, lons, lats, dam_lon=lons[7], dam_lat=lats[8])
    assert aoi["properties"]["selection"] == "dam_connected_component"
    # dam far from any water → loud failure, not a silent wrong AOI
    with pytest.raises(ValueError, match="no water pixel within"):
        aoi_bbox_from_occurrence(occ, lons, lats, dam_lon=lons[0], dam_lat=lats[0])
