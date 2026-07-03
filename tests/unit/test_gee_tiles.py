"""Tile-URL cache + GEE-unavailable behaviour (dashboard spec endpoint 2). No live GEE."""

from datetime import UTC, datetime, timedelta

import pytest

from api import gee_tiles


@pytest.fixture(autouse=True)
def clear_cache():
    gee_tiles._CACHE.clear()
    yield
    gee_tiles._CACHE.clear()


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
