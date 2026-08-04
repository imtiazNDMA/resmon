from io import BytesIO
from pathlib import Path

import numpy as np
import rasterio
from api.sar_assets import (
    SarAsset,
    configure_rasterio_environment,
    file_metadata,
    find_asset,
    init_catalog,
    list_manifest,
    render_tile,
    upsert_asset,
)
from PIL import Image
from rasterio.transform import from_bounds


def _asset(tmp_path: Path, **overrides) -> SarAsset:
    vv = tmp_path / "vv.tif"
    vh = tmp_path / "vh.tif"
    water = tmp_path / "water_mask.tif"
    for path in (vv, vh, water):
        if not path.exists():
            path.write_bytes(b"placeholder")
    values = {
        "reservoir_id": "pong",
        "acquisition_date": "2020-01-05",
        "scene_id": "S1A_TEST",
        "vv_path": vv,
        "vh_path": vh,
        "water_mask_path": water,
        "bounds": (74.0, 31.0, 76.0, 33.0),
        "min_zoom": 8,
        "max_zoom": 14,
        "status": "ready",
    }
    values.update(overrides)
    return SarAsset(**values)


def _write_tif(path: Path, data: np.ndarray, *, nodata: float | int | None = None) -> None:
    configure_rasterio_environment()
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=from_bounds(-180, -85, 180, 85, data.shape[1], data.shape[0]),
        nodata=nodata,
    ) as dst:
        dst.write(data, 1)


def _png(bytes_: bytes) -> Image.Image:
    return Image.open(BytesIO(bytes_))


def test_init_catalog_creates_sqlite_file(tmp_path):
    db_path = tmp_path / "catalog.sqlite"

    init_catalog(db_path)

    assert db_path.exists()


def test_find_asset_returns_ready_asset_with_required_composite_files(tmp_path):
    db_path = tmp_path / "catalog.sqlite"
    upsert_asset(_asset(tmp_path), db_path)

    asset = find_asset("pong", "2020-01-05", "false_color", db_path)

    assert asset is not None
    assert asset.scene_id == "S1A_TEST"
    assert asset.bounds == (74.0, 31.0, 76.0, 33.0)


def test_find_asset_returns_none_when_required_file_missing(tmp_path):
    db_path = tmp_path / "catalog.sqlite"
    missing_water = tmp_path / "missing-water-mask.tif"
    upsert_asset(_asset(tmp_path, water_mask_path=missing_water), db_path)

    assert find_asset("pong", "2020-01-05", "water_class", db_path) is None
    assert find_asset("pong", "2020-01-05", "vh", db_path) is not None


def test_find_asset_ignores_non_ready_rows(tmp_path):
    db_path = tmp_path / "catalog.sqlite"
    upsert_asset(_asset(tmp_path, status="pending"), db_path)

    assert find_asset("pong", "2020-01-05", "vh", db_path) is None


def test_upsert_asset_replaces_existing_row(tmp_path):
    db_path = tmp_path / "catalog.sqlite"
    upsert_asset(_asset(tmp_path, min_zoom=8), db_path)
    upsert_asset(_asset(tmp_path, min_zoom=10), db_path)

    asset = find_asset("pong", "2020-01-05", "vh", db_path)

    assert asset is not None
    assert asset.min_zoom == 10


def test_find_asset_rejects_checksum_mismatch(tmp_path):
    db_path = tmp_path / "catalog.sqlite"
    vh = tmp_path / "vh.tif"
    vh.write_bytes(b"original")
    size, sha256 = file_metadata(vh)
    upsert_asset(_asset(tmp_path, vh_path=vh, vh_size_bytes=size, vh_sha256=sha256), db_path)

    vh.write_bytes(b"modified")

    assert find_asset("pong", "2020-01-05", "vh", db_path) is None


def test_list_manifest_omits_checksum_mismatch(tmp_path):
    db_path = tmp_path / "catalog.sqlite"
    vh = tmp_path / "vh.tif"
    vh.write_bytes(b"original")
    size, sha256 = file_metadata(vh)
    upsert_asset(_asset(tmp_path, vh_path=vh, vh_size_bytes=size, vh_sha256=sha256), db_path)

    vh.write_bytes(b"modified")

    assert list_manifest("pong", db_path) == []


def test_list_manifest_reports_renderable_composites(tmp_path):
    db_path = tmp_path / "catalog.sqlite"
    upsert_asset(_asset(tmp_path), db_path)

    entries = list_manifest("pong", db_path)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.reservoir_id == "pong"
    assert entry.acquisition_date == "2020-01-05"
    assert entry.composites == ("vh", "vv", "false_color", "water_class", "vv_vh_contrast")


def test_list_manifest_omits_assets_without_renderable_files(tmp_path):
    db_path = tmp_path / "catalog.sqlite"
    upsert_asset(
        _asset(
            tmp_path,
            vv_path=tmp_path / "missing-vv.tif",
            vh_path=None,
            water_mask_path=tmp_path / "missing-water.tif",
        ),
        db_path,
    )

    assert list_manifest("pong", db_path) == []


def test_render_tile_from_local_vh_raster(tmp_path):
    vh = tmp_path / "vh.tif"
    _write_tif(vh, np.full((32, 32), -15.0, dtype="float32"))
    asset = _asset(tmp_path, vh_path=vh)

    tile = _png(render_tile(asset, "vh", 0, 0, 0))

    assert tile.mode == "RGBA"
    assert tile.size == (256, 256)
    assert tile.getpixel((128, 128))[3] == 255


def test_render_tile_false_color_from_local_vv_vh_rasters(tmp_path):
    vv = tmp_path / "vv.tif"
    vh = tmp_path / "vh.tif"
    _write_tif(vv, np.full((32, 32), -10.0, dtype="float32"))
    _write_tif(vh, np.full((32, 32), -20.0, dtype="float32"))
    asset = _asset(tmp_path, vv_path=vv, vh_path=vh)

    tile = _png(render_tile(asset, "false_color", 0, 0, 0))

    pixel = tile.getpixel((128, 128))

    assert tile.size == (256, 256)
    assert pixel[3] == 255
    assert pixel[:3] != (pixel[0], pixel[0], pixel[0])


def test_render_tile_water_class_palette(tmp_path):
    water = tmp_path / "water_mask.tif"
    _write_tif(water, np.ones((32, 32), dtype="uint8"), nodata=255)
    asset = _asset(tmp_path, water_mask_path=water)

    tile = _png(render_tile(asset, "water_class", 0, 0, 0))

    assert tile.getpixel((128, 128)) == (0, 71, 255, 255)
