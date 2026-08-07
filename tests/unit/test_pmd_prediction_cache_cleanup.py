from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from scripts.cleanup_pmd_prediction_cache import cleanup_cache


def test_cleanup_cache_removes_only_old_prediction_artifacts(tmp_path):
    old_png = tmp_path / "old.png"
    old_json = tmp_path / "old.json"
    old_tif = tmp_path / "old.tif"
    fresh_png = tmp_path / "fresh.png"
    for path in (old_png, old_json, old_tif, fresh_png):
        path.write_text("x")

    old_time = (datetime.now(UTC) - timedelta(days=30)).timestamp()
    for path in (old_png, old_json, old_tif):
        os.utime(path, (old_time, old_time))

    dry_run = cleanup_cache(tmp_path, older_than_days=14, dry_run=True)
    assert sorted(path.name for path in dry_run) == ["old.json", "old.png"]
    assert old_png.exists()

    removed = cleanup_cache(tmp_path, older_than_days=14, dry_run=False)
    assert sorted(path.name for path in removed) == ["old.json", "old.png"]
    assert not old_png.exists()
    assert not old_json.exists()
    assert old_tif.exists()
    assert fresh_png.exists()
