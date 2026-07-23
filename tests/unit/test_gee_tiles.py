"""Tile-URL cache + GEE-unavailable behaviour (dashboard spec endpoint 2). No live GEE."""

from datetime import UTC, datetime, timedelta

import pytest

from api import gee_tiles


@pytest.fixture(autouse=True)
def clear_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(gee_tiles, "_DISK_CACHE_PATH", tmp_path / "sar_tiles.json")
    gee_tiles._DISK_CACHE_LOADED = False
    gee_tiles._CACHE.clear()
    yield
    gee_tiles._CACHE.clear()
    gee_tiles._DISK_CACHE_LOADED = False


def test_cache_hit_within_ttl(monkeypatch):
    calls = []

    def fake_mint(scene_id: str):
        calls.append(scene_id)
        return ("https://tiles/x/{z}/{x}/{y}", datetime.now(UTC) + timedelta(hours=3))

    monkeypatch.setattr(gee_tiles, "mint_tile", fake_mint)
    url1, _ = gee_tiles.get_cached_tile("gobind_sagar", "2020-01-05", "S1A_X")
    url2, _ = gee_tiles.get_cached_tile("gobind_sagar", "2020-01-05", "S1A_X")
    assert url1 == url2
    assert calls == ["S1A_X"]  # second call served from cache


def test_expired_entry_reminted(monkeypatch):
    when = [datetime.now(UTC) - timedelta(minutes=1)]  # already expired

    def fake_mint(scene_id: str):
        return ("https://tiles/x/{z}/{x}/{y}", when[0])

    monkeypatch.setattr(gee_tiles, "mint_tile", fake_mint)
    gee_tiles.get_cached_tile("pong", "2020-01-05", "S1A_Y")
    when[0] = datetime.now(UTC) + timedelta(hours=3)
    _, exp = gee_tiles.get_cached_tile("pong", "2020-01-05", "S1A_Y")
    assert exp == when[0]  # re-minted, not served stale


def test_gee_unavailable_raises(monkeypatch):
    def broken_mint(scene_id: str):
        raise gee_tiles.GeeUnavailable("no credentials")

    monkeypatch.setattr(gee_tiles, "mint_tile", broken_mint)
    with pytest.raises(gee_tiles.GeeUnavailable):
        gee_tiles.get_cached_tile("thein", "2020-01-05", "S1A_Z")


def test_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(gee_tiles, "_CACHE_MAX", 2)

    def fake_mint(scene_id: str):
        return (
            f"https://tiles/{scene_id}/{{z}}/{{x}}/{{y}}",
            datetime.now(UTC) + timedelta(hours=3),
        )

    monkeypatch.setattr(gee_tiles, "mint_tile", fake_mint)
    gee_tiles.get_cached_tile("gobind_sagar", "2020-01-01", "S1A_1")
    gee_tiles.get_cached_tile("gobind_sagar", "2020-01-02", "S1A_2")
    gee_tiles.get_cached_tile("gobind_sagar", "2020-01-03", "S1A_3")
    assert len(gee_tiles._CACHE) == 2
    assert ("gobind_sagar", "2020-01-01", "S1A_1") not in gee_tiles._CACHE


def test_disk_cache_loaded_without_remint(monkeypatch):
    calls = []

    def fake_mint(scene_id: str):
        calls.append(scene_id)
        return (
            f"https://tiles/{scene_id}/{{z}}/{{x}}/{{y}}",
            datetime.now(UTC) + timedelta(hours=3),
        )

    monkeypatch.setattr(gee_tiles, "mint_tile", fake_mint)
    url1, _ = gee_tiles.get_cached_tile("pong", "2020-01-05", "S1A_DISK")

    gee_tiles._CACHE.clear()
    gee_tiles._DISK_CACHE_LOADED = False
    url2, _ = gee_tiles.get_cached_tile("pong", "2020-01-05", "S1A_DISK")

    assert url1 == url2
    assert calls == ["S1A_DISK"]


def test_raster_cache_loaded_without_refetch(monkeypatch, tmp_path):
    monkeypatch.setattr(gee_tiles, "_RASTER_CACHE_ROOT", tmp_path / "rasters")
    calls = []

    class FakeResponse:
        content = b"tile-bytes"

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url: str):
            calls.append(url)
            return FakeResponse()

    monkeypatch.setattr(gee_tiles.httpx, "Client", FakeClient)

    first = gee_tiles.get_cached_raster(
        "https://tiles/{z}/{x}/{y}", "pong", "2020-01-05", 8, 10, 20
    )
    second = gee_tiles.get_cached_raster(
        "https://tiles/{z}/{x}/{y}", "pong", "2020-01-05", 8, 10, 20
    )

    assert first == second == b"tile-bytes"
    assert calls == ["https://tiles/8/10/20"]
