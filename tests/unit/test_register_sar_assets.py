from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds

from scripts.register_sar_assets import main, register_asset


def _write_tif(path: Path) -> None:
    from api.sar_assets import configure_rasterio_environment

    configure_rasterio_environment()
    data = np.full((16, 16), -15.0, dtype="float32")
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


def test_register_asset_validates_and_writes_catalog(tmp_path):
    catalog = tmp_path / "sar_assets.sqlite"
    vh = tmp_path / "vh.tif"
    _write_tif(vh)

    asset = register_asset(
        reservoir_id="pong",
        acquisition_date="2020-01-05",
        scene_id="S1A_TEST",
        vh_path=vh,
        catalog_path=catalog,
    )

    assert asset.bounds == (74.0, 31.0, 76.0, 33.0)
    with sqlite3.connect(catalog) as conn:
        row = conn.execute(
            "SELECT reservoir_id, vh_path, vh_size_bytes, vh_sha256 FROM sar_asset"
        ).fetchone()
    assert row[0:2] == ("pong", str(vh))
    assert row[2] == vh.stat().st_size
    assert len(row[3]) == 64


def test_register_asset_dry_run_does_not_write_catalog(tmp_path):
    catalog = tmp_path / "sar_assets.sqlite"
    vh = tmp_path / "vh.tif"
    _write_tif(vh)

    register_asset(
        reservoir_id="pong",
        acquisition_date="2020-01-05",
        scene_id="S1A_TEST",
        vh_path=vh,
        catalog_path=catalog,
        dry_run=True,
    )

    assert not catalog.exists()


def test_register_asset_rejects_missing_raster(tmp_path):
    missing = tmp_path / "missing.tif"

    try:
        register_asset(
            reservoir_id="pong",
            acquisition_date="2020-01-05",
            scene_id="S1A_TEST",
            vh_path=missing,
            catalog_path=tmp_path / "catalog.sqlite",
        )
    except ValueError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("missing raster should fail validation")


def test_cli_registers_asset(tmp_path, capsys):
    catalog = tmp_path / "sar_assets.sqlite"
    vh = tmp_path / "vh.tif"
    _write_tif(vh)

    code = main(
        [
            "--reservoir",
            "pong",
            "--date",
            "2020-01-05",
            "--scene-id",
            "S1A_TEST",
            "--vh",
            str(vh),
            "--catalog",
            str(catalog),
        ]
    )

    assert code == 0
    assert "registered: pong 2020-01-05 S1A_TEST" in capsys.readouterr().out
    assert catalog.exists()


def test_cli_returns_2_for_invalid_input(tmp_path, capsys):
    code = main(
        [
            "--reservoir",
            "pong",
            "--date",
            "2020-01-05",
            "--scene-id",
            "S1A_TEST",
            "--vh",
            str(tmp_path / "missing.tif"),
            "--catalog",
            str(tmp_path / "catalog.sqlite"),
        ]
    )

    assert code == 2
    assert "does not exist" in capsys.readouterr().err
