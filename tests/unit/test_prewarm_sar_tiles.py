from __future__ import annotations

from pathlib import Path

from api.sar_assets import SarAsset, upsert_asset

from api import gee_tiles
from scripts.prewarm_sar_tiles import _tiles_for_bounds, main, prewarm_demo_tiles, prewarm_tiles


def _asset(tmp_path: Path) -> SarAsset:
    vh = tmp_path / "vh.tif"
    vh.write_bytes(b"placeholder")
    return SarAsset(
        reservoir_id="pong",
        acquisition_date="2020-01-05",
        scene_id="S1A_TEST",
        vv_path=None,
        vh_path=vh,
        water_mask_path=None,
        bounds=(-1.0, -1.0, 1.0, 1.0),
        min_zoom=0,
        max_zoom=2,
        status="ready",
    )


def _asset_for_date(tmp_path: Path, date: str) -> SarAsset:
    date_dir = tmp_path / date
    date_dir.mkdir()
    asset = _asset(date_dir)
    return SarAsset(
        reservoir_id=asset.reservoir_id,
        acquisition_date=date,
        scene_id=f"S1A_TEST_{date}",
        vv_path=asset.vv_path,
        vh_path=asset.vh_path,
        water_mask_path=asset.water_mask_path,
        bounds=asset.bounds,
        min_zoom=asset.min_zoom,
        max_zoom=asset.max_zoom,
        status=asset.status,
    )


def test_tiles_for_bounds_covers_intersecting_xyz_tiles():
    assert _tiles_for_bounds((-1.0, -1.0, 1.0, 1.0), 1, 1) == [
        (1, 0, 0),
        (1, 0, 1),
        (1, 1, 0),
        (1, 1, 1),
    ]


def test_prewarm_tiles_renders_and_writes_cache(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.sqlite"
    upsert_asset(_asset(tmp_path), catalog)
    monkeypatch.setattr(gee_tiles, "_RASTER_CACHE_ROOT", tmp_path / "cache")
    rendered: list[tuple[int, int, int]] = []

    def render(asset: SarAsset, composite: str, z: int, x: int, y: int) -> bytes:
        rendered.append((z, x, y))
        return b"png"

    result = prewarm_tiles(
        reservoir_id="pong",
        acquisition_date="2020-01-05",
        composite="vh",
        min_zoom=0,
        max_zoom=0,
        catalog_path=catalog,
        renderer=render,
    )

    assert result.tiles == 1
    assert result.rendered == 1
    assert rendered == [(0, 0, 0)]
    assert gee_tiles.get_cached_raster_content("pong", "2020-01-05", "vh", 0, 0, 0) == b"png"


def test_prewarm_tiles_skips_existing_cache(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.sqlite"
    upsert_asset(_asset(tmp_path), catalog)
    monkeypatch.setattr(gee_tiles, "_RASTER_CACHE_ROOT", tmp_path / "cache")
    gee_tiles.put_cached_raster_content("pong", "2020-01-05", "vh", 0, 0, 0, b"cached")

    result = prewarm_tiles(
        reservoir_id="pong",
        acquisition_date="2020-01-05",
        composite="vh",
        min_zoom=0,
        max_zoom=0,
        catalog_path=catalog,
        renderer=lambda *_: (_ for _ in ()).throw(AssertionError("should not render")),
    )

    assert result.tiles == 1
    assert result.rendered == 0
    assert result.skipped == 1


def test_cli_dry_run_counts_tiles_without_writing(tmp_path, capsys, monkeypatch):
    catalog = tmp_path / "catalog.sqlite"
    upsert_asset(_asset(tmp_path), catalog)
    monkeypatch.setattr(gee_tiles, "_RASTER_CACHE_ROOT", tmp_path / "cache")

    code = main(
        [
            "--reservoir",
            "pong",
            "--date",
            "2020-01-05",
            "--composite",
            "vh",
            "--min-zoom",
            "0",
            "--max-zoom",
            "0",
            "--catalog",
            str(catalog),
            "--dry-run",
        ]
    )

    assert code == 0
    assert "would prewarm: pong 2020-01-05 vh tiles=1" in capsys.readouterr().out
    assert not (tmp_path / "cache").exists()


def test_prewarm_demo_tiles_uses_latest_plus_nearby_dates(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.sqlite"
    for date in ("2020-01-01", "2020-01-05", "2020-01-10"):
        upsert_asset(_asset_for_date(tmp_path, date), catalog)
    monkeypatch.setattr(gee_tiles, "_RASTER_CACHE_ROOT", tmp_path / "cache")

    results = prewarm_demo_tiles(
        reservoir_id="pong",
        composite="vh",
        min_zoom=0,
        max_zoom=0,
        nearby_dates=1,
        catalog_path=catalog,
        renderer=lambda *_: b"png",
    )

    assert [result.acquisition_date for result in results] == ["2020-01-05", "2020-01-10"]
    assert [result.rendered for result in results] == [1, 1]


def test_cli_latest_nearby_prints_total(tmp_path, capsys, monkeypatch):
    catalog = tmp_path / "catalog.sqlite"
    for date in ("2020-01-01", "2020-01-05"):
        upsert_asset(_asset_for_date(tmp_path, date), catalog)
    monkeypatch.setattr(gee_tiles, "_RASTER_CACHE_ROOT", tmp_path / "cache")

    code = main(
        [
            "--reservoir",
            "pong",
            "--composite",
            "vh",
            "--min-zoom",
            "0",
            "--max-zoom",
            "0",
            "--catalog",
            str(catalog),
            "--latest-nearby",
            "1",
            "--dry-run",
        ]
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "would prewarm: pong 2020-01-01 vh tiles=1" in out
    assert "would prewarm: pong 2020-01-05 vh tiles=1" in out
    assert "total: dates=2 tiles=2" in out


def test_cli_requires_date_without_latest_nearby(capsys):
    code = main(["--reservoir", "pong", "--min-zoom", "0", "--max-zoom", "0"])

    assert code == 2
    assert "--date is required" in capsys.readouterr().err
