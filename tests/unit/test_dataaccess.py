"""Backend contract test: every backend satisfies the same interface (§4.4 swappability)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest
from pipelines_common.dataaccess import (
    DataAccessBackend,
    FixtureBackend,
    GEEBackend,
    get_backend,
)


def test_factory_returns_requested_backend():
    assert isinstance(get_backend("fixture"), FixtureBackend)
    assert isinstance(get_backend("gee"), GEEBackend)
    assert isinstance(get_backend("fixture"), DataAccessBackend)


def test_unknown_backend_raises():
    with pytest.raises(ValueError, match="Unknown data-access backend"):
        get_backend("does-not-exist")


def test_fixture_backend_shapes():
    b = get_backend("fixture")
    s, e = date(2025, 8, 1), date(2025, 8, 15)
    s1 = b.get_s1_grd({}, s, e, orbit=12, pass_dir="ASC")
    assert {"VV", "VH"} <= set(s1.data_vars)
    assert s1.attrs["orbit_relative"] == 12 and s1.attrs["pass_direction"] == "ASC"
    dem = b.get_dem({})
    assert "DEM" in dem.data_vars
    scenes = b.list_scenes("COPERNICUS/S1_GRD", {}, s, e)
    assert scenes and "acquisition_date" in scenes[0]


def test_fixture_s1_scene_is_physically_plausible():
    """The canned S1 scene must look like SAR dB, not 0 dB everywhere: a specular
    low-VH water mode inside brighter land clutter, co-pol above cross-pol."""
    b = get_backend("fixture")
    s1 = b.get_s1_grd({}, date(2025, 8, 1), date(2025, 8, 5), orbit=12, pass_dir="ASC")
    vh = s1["VH"].values
    vv = s1["VV"].values
    assert np.isfinite(vh).all() and np.isfinite(vv).all()
    assert not np.allclose(vh, 0.0)
    assert vh.min() < -18.0  # water mode present (~ -22 dB)
    assert vh.max() > -15.0  # land mode present (~ -12 dB)
    assert float(vv.mean()) > float(vh.mean())  # co-pol brighter than cross-pol
    # bimodal enough for an extractor to threshold: both modes carry real mass
    assert (vh < -18.0).mean() > 0.1
    assert (vh > -15.0).mean() > 0.3


def test_gee_backend_satisfies_interface_without_credentials():
    # Importable/instantiable without GEE installed; methods fail loudly only when used.
    g = get_backend("gee")
    assert isinstance(g, DataAccessBackend)
    assert g.name == "gee"
