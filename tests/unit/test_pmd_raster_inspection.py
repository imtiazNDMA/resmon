from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from scripts.inspect_pmd_prediction_raster import inspect_raster


def test_inspect_raster_emits_contract_evidence(tmp_path):
    raster_path = tmp_path / "hourly_precip.tif"
    values = np.array([[1.0, 2.0], [9999.0, 4.0]], dtype="float32")
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        transform=from_origin(73.0, 34.0, 0.1, 0.1),
        nodata=9999.0,
    ) as dataset:
        dataset.write(values, 1)

    evidence = inspect_raster(raster_path, element_key="pmd_pred_hourtpe")

    assert evidence["element"]["data_type"] == "WRFPRS"
    assert evidence["element"]["element"] == "HOURTPE"
    raster = evidence["raster"]
    assert raster["driver"] == "GTiff"
    assert raster["crs"] is None
    assert raster["band_count"] == 1
    assert raster["nodata"] == 9999.0
    assert raster["bounds"] == [73.0, 33.8, 73.2, 34.0]
    stats = raster["band_stats"][0]
    assert stats["band"] == 1
    assert stats["valid_pixels"] == 3
    assert stats["min"] == 1.0
    assert stats["p50"] == 2.0
    assert stats["p95"] == pytest.approx(3.8)
    assert stats["max"] == 4.0
