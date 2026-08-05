from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds

from scripts.backfill_sar_assets import (
    ROOT,
    SceneSpec,
    backfill_scene_assets,
    backfill_scene_batch,
    default_out_root,
    main,
)

AOI = {
    "type": "Polygon",
    "coordinates": [[[74.0, 31.0], [76.0, 31.0], [76.0, 33.0], [74.0, 33.0], [74.0, 31.0]]],
}


def _tif_bytes(tmp_path: Path, value: float) -> bytes:
    from api.sar_assets import configure_rasterio_environment

    configure_rasterio_environment()
    path = tmp_path / f"{value}.tif"
    data = np.full((16, 16), value, dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=from_bounds(74.0, 31.0, 76.0, 33.0, data.shape[1], data.shape[0]),
    ) as dst:
        dst.write(data, 1)
    return path.read_bytes()


def test_backfill_scene_assets_downloads_and_registers(tmp_path):
    catalog = tmp_path / "catalog.sqlite"
    payloads = {
        "mock://VV": _tif_bytes(tmp_path, -10.0),
        "mock://VH": _tif_bytes(tmp_path, -20.0),
        "mock://water_mask": _tif_bytes(tmp_path, 1.0),
    }
    requested = []

    def url_factory(scene_id: str, band: str, *_args):
        assert scene_id == "S1A_TEST"
        return f"mock://{band}"

    def downloader(url: str) -> bytes:
        requested.append(url)
        return payloads[url]

    result = backfill_scene_assets(
        reservoir_id="pong",
        acquisition_date="2020-01-05",
        scene_id="S1A_TEST",
        aoi_geojson=AOI,
        out_root=tmp_path / "sar_cog",
        catalog_path=catalog,
        downloader=downloader,
        url_factory=url_factory,
    )

    assert requested == ["mock://VV", "mock://VH", "mock://water_mask"]
    assert result.registered is True
    assert result.vv_path.exists()
    assert result.vh_path.exists()
    assert result.water_mask_path is not None and result.water_mask_path.exists()
    with sqlite3.connect(catalog) as conn:
        row = conn.execute(
            "SELECT reservoir_id, vv_path, vh_path, water_mask_path FROM sar_asset"
        ).fetchone()
    assert row == ("pong", str(result.vv_path), str(result.vh_path), str(result.water_mask_path))


def test_backfill_scene_assets_dry_run_does_not_download_or_write(tmp_path):
    def fail_downloader(_url: str) -> bytes:
        raise AssertionError("dry-run should not download")

    result = backfill_scene_assets(
        reservoir_id="pong",
        acquisition_date="2020-01-05",
        scene_id="S1A_TEST",
        aoi_geojson=AOI,
        out_root=tmp_path / "sar_cog",
        dry_run=True,
        downloader=fail_downloader,
    )

    assert result.registered is False
    assert not result.vv_path.exists()


def test_backfill_scene_batch_downloads_each_scene(tmp_path):
    payloads = {
        "mock://S1A_1/VV": _tif_bytes(tmp_path, -10.0),
        "mock://S1A_1/VH": _tif_bytes(tmp_path, -20.0),
        "mock://S1A_2/VV": _tif_bytes(tmp_path, -11.0),
        "mock://S1A_2/VH": _tif_bytes(tmp_path, -21.0),
    }
    requested = []

    def url_factory(scene_id: str, band: str, *_args):
        return f"mock://{scene_id}/{band}"

    def downloader(url: str) -> bytes:
        requested.append(url)
        return payloads[url]

    results = backfill_scene_batch(
        reservoir_id="pong",
        scenes=[SceneSpec("S1A_1", "2020-01-05"), SceneSpec("S1A_2", "2020-01-17")],
        aoi_geojson=AOI,
        out_root=tmp_path / "sar_cog",
        catalog_path=tmp_path / "catalog.sqlite",
        include_water_mask=False,
        downloader=downloader,
        url_factory=url_factory,
    )

    assert requested == ["mock://S1A_1/VV", "mock://S1A_1/VH", "mock://S1A_2/VV", "mock://S1A_2/VH"]
    assert [r.registered for r in results] == [True, True]


def test_backfill_scene_batch_skips_existing_outputs(tmp_path):
    scene_dir = tmp_path / "sar_cog" / "pong" / "2020-01-05"
    scene_dir.mkdir(parents=True)
    (scene_dir / "vv.tif").write_bytes(b"existing")
    (scene_dir / "vh.tif").write_bytes(b"existing")

    def fail_downloader(_url: str) -> bytes:
        raise AssertionError("existing outputs should be skipped")

    results = backfill_scene_batch(
        reservoir_id="pong",
        scenes=[SceneSpec("S1A_1", "2020-01-05")],
        aoi_geojson=AOI,
        out_root=tmp_path / "sar_cog",
        include_water_mask=False,
        downloader=fail_downloader,
    )

    assert results[0].skipped is True
    assert results[0].registered is False


def test_cli_dry_run_reports_target_paths(tmp_path, capsys):
    aoi = tmp_path / "aoi.geojson"
    aoi.write_text(json.dumps(AOI), encoding="utf-8")

    code = main(
        [
            "--reservoir",
            "pong",
            "--date",
            "2020-01-05",
            "--scene-id",
            "S1A_TEST",
            "--aoi",
            str(aoi),
            "--out-root",
            str(tmp_path / "sar_cog"),
            "--dry-run",
        ]
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "would write:" in out
    assert "vv.tif" in out
    assert "vh.tif" in out


def test_default_out_root_uses_sar_cog_root_env(monkeypatch, tmp_path):
    from core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SAR_COG_ROOT", "custom/sar")
    try:
        assert default_out_root() == ROOT / "custom" / "sar"
        monkeypatch.setenv("SAR_COG_ROOT", str(tmp_path / "absolute-sar"))
        get_settings.cache_clear()
        assert default_out_root() == tmp_path / "absolute-sar"
    finally:
        get_settings.cache_clear()


def test_cli_requires_complete_single_scene_args(tmp_path, capsys):
    aoi = tmp_path / "aoi.geojson"
    aoi.write_text(json.dumps(AOI), encoding="utf-8")

    code = main(
        [
            "--reservoir",
            "pong",
            "--scene-id",
            "S1A_TEST",
            "--aoi",
            str(aoi),
            "--dry-run",
        ]
    )

    assert code == 2
    assert "requires both --scene-id and --date" in capsys.readouterr().err
