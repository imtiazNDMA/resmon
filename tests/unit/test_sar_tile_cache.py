from __future__ import annotations

import os

from api import gee_tiles
from scripts.sar_tile_cache import main


def test_raster_cache_stats_counts_png_tiles_only(tmp_path):
    root = tmp_path / "cache"
    (root / "a").mkdir(parents=True)
    (root / "a" / "1.png").write_bytes(b"123")
    (root / "a" / "ignore.tmp").write_bytes(b"12345")
    (root / "b").mkdir()
    (root / "b" / "2.png").write_bytes(b"1234")

    stats = gee_tiles.raster_cache_stats(root)

    assert stats.tiles == 2
    assert stats.bytes == 7


def test_cleanup_raster_cache_deletes_oldest_tiles_until_under_limit(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    old = root / "old.png"
    new = root / "new.png"
    old.write_bytes(b"12345")
    new.write_bytes(b"12345")
    os.utime(old, (100, 100))
    os.utime(new, (200, 200))

    stats = gee_tiles.cleanup_raster_cache(5, root)

    assert stats.tiles == 1
    assert stats.bytes == 5
    assert not old.exists()
    assert new.exists()


def test_cache_cli_reports_stats(tmp_path, capsys):
    root = tmp_path / "cache"
    root.mkdir()
    (root / "tile.png").write_bytes(b"123")

    code = main(["--root", str(root), "--stats"])

    assert code == 0
    assert "cache stats:" in capsys.readouterr().out


def test_cache_cli_cleanup_reports_remaining_usage(tmp_path, capsys):
    root = tmp_path / "cache"
    root.mkdir()
    (root / "tile.png").write_bytes(b"123")

    code = main(["--root", str(root), "--cleanup-max-mb", "0"])

    assert code == 0
    out = capsys.readouterr().out
    assert "cache cleanup:" in out
    assert "tiles=0" in out
