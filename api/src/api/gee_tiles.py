"""Live Sentinel-1 tile URLs for the map (dashboard spec endpoint 2).

The only optional-GEE corner of the API: everything else runs credential-free.
EE map ids expire (~4 h), so mints are cached per (reservoir, date) with the
expiry advertised to clients, minus a safety margin. GeeUnavailable -> the route
503s and the frontend falls back to basemap + AOI outline (honesty state, spec).
"""

from __future__ import annotations

import json
import os
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from core.config import get_settings

_CACHE: OrderedDict[tuple[str, str, str], tuple[str, datetime]] = OrderedDict()
_CACHE_MAX = 256
_EE_INITIALIZED = False
_EE_KEY_INFO: dict | None = None
_EE_KEY_FILE: str | None = None
_SAFETY = timedelta(minutes=10)
_VIS = {"bands": ["VH"], "min": -25.0, "max": -5.0}  # dark-water SAR styling
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DISK_CACHE_PATH = _REPO_ROOT / ".cache" / "sar_tiles.json"
_RASTER_CACHE_ROOT = _REPO_ROOT / ".cache" / "sar_rasters"
_DISK_CACHE_LOADED = False


class GeeUnavailable(RuntimeError):
    """GEE credentials missing or initialisation failed — degrade, don't crash."""


def _load_key_info() -> tuple[str, dict]:
    global _EE_KEY_FILE, _EE_KEY_INFO
    settings = get_settings()
    key_file = settings.gee_sa_key_file
    dev_key = _REPO_ROOT / "geeservice.json"
    if not key_file and settings.app_env == "dev" and dev_key.exists():
        key_file = str(dev_key)
    if not key_file:
        raise GeeUnavailable("GEE_SA_KEY_FILE must be configured to mint live SAR tiles")
    if not os.path.exists(key_file):
        raise GeeUnavailable(f"no GEE key file at {key_file}")
    if _EE_KEY_INFO is None or _EE_KEY_FILE != key_file:
        with open(key_file, encoding="utf-8") as fh:
            _EE_KEY_INFO = json.load(fh)
        _EE_KEY_FILE = key_file
    return key_file, _EE_KEY_INFO


def _ensure_ee_initialized() -> None:
    global _EE_INITIALIZED
    if _EE_INITIALIZED:
        return
    try:
        import ee  # noqa: PLC0415 — optional dependency corner

        key_file, info = _load_key_info()
        ee.Initialize(
            ee.ServiceAccountCredentials(info["client_email"], key_file),
            project=info["project_id"],
        )
        _EE_INITIALIZED = True
    except GeeUnavailable:
        raise
    except Exception as exc:
        raise GeeUnavailable(str(exc)) from exc


def mint_tile(scene_id: str) -> tuple[str, datetime]:
    """One EE round-trip: scene asset -> map id -> tile URL template + expiry."""
    try:
        import ee  # noqa: PLC0415 — optional dependency corner

        _ensure_ee_initialized()
        img = ee.Image(f"COPERNICUS/S1_GRD/{scene_id}")
        mapid = img.getMapId(_VIS)
        url = str(mapid["tile_fetcher"].url_format)
        # EE does not return an expiry; map ids last ~4 h — advertise 3.5 h.
        return url, datetime.now(UTC) + timedelta(hours=3, minutes=30)
    except GeeUnavailable:
        raise
    except Exception as exc:  # ee import/auth/asset errors — all mean "degrade"
        raise GeeUnavailable(str(exc)) from exc


def _cache_key(rid: str, date: str, scene_id: str) -> tuple[str, str, str]:
    return (rid, date, scene_id)


def _load_disk_cache() -> None:
    global _DISK_CACHE_LOADED
    if _DISK_CACHE_LOADED:
        return
    _DISK_CACHE_LOADED = True
    if not _DISK_CACHE_PATH.exists():
        return
    try:
        raw = json.loads(_DISK_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    now = datetime.now(UTC)
    for key, item in raw.items():
        try:
            rid, date, scene_id = key.split("|", 2)
            exp = datetime.fromisoformat(item["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            if exp - _SAFETY > now:
                _CACHE[_cache_key(rid, date, scene_id)] = (str(item["tile_url"]), exp)
        except (KeyError, TypeError, ValueError):
            continue


def _save_disk_cache() -> None:
    try:
        _DISK_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "|".join(key): {"tile_url": value[0], "expires_at": value[1].isoformat()}
            for key, value in _CACHE.items()
        }
        tmp = _DISK_CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(_DISK_CACHE_PATH)
    except OSError:
        return


def get_cached_tile(rid: str, date: str, scene_id: str) -> tuple[str, datetime]:
    _load_disk_cache()
    key = _cache_key(rid, date, scene_id)
    hit = _CACHE.get(key)
    now = datetime.now(UTC)
    if hit and hit[1] - _SAFETY > now:
        _CACHE.move_to_end(key)
        return hit
    fresh = mint_tile(scene_id)
    _CACHE[key] = fresh
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    _save_disk_cache()
    return fresh


def _raster_path(rid: str, date: str, z: int, x: int, y: int) -> Path:
    safe_rid = "".join(ch for ch in rid if ch.isalnum() or ch in "_-")
    safe_date = "".join(ch for ch in date if ch.isalnum() or ch in "_-")
    return _RASTER_CACHE_ROOT / safe_rid / safe_date / str(z) / str(x) / f"{y}.png"


def get_cached_raster(tile_url: str, rid: str, date: str, z: int, x: int, y: int) -> bytes:
    """Fetch one XYZ tile through the API and persist it for later playback."""
    path = _raster_path(rid, date, z, x, y)
    try:
        if path.exists():
            return path.read_bytes()
        remote_url = tile_url.format(z=z, x=x, y=y)
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            response = client.get(remote_url)
            response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(response.content)
        tmp.replace(path)
        return response.content
    except Exception as exc:
        raise GeeUnavailable(str(exc)) from exc
