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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from core.config import get_settings

_CACHE: OrderedDict[tuple[str, str, str, str], tuple[str, datetime]] = OrderedDict()
_CACHE_MAX = 256
_EE_INITIALIZED = False
_EE_KEY_INFO: dict | None = None
_EE_KEY_FILE: str | None = None
_SAFETY = timedelta(minutes=10)
DEFAULT_COMPOSITE = "vh"
_COMPOSITES: dict[str, dict] = {
    "vh": {"bands": ["VH"], "min": -25.0, "max": -5.0},
    "vv": {"bands": ["VV"], "min": -20.0, "max": 0.0},
    "false_color": {
        "bands": ["VV", "VH", "VV_minus_VH"],
        "min": [-24.0, -30.0, 0.0],
        "max": [0.0, -4.0, 14.0],
        "gamma": 1.15,
    },
    "water_class": {
        "bands": ["water_class"],
        "min": 0,
        "max": 1,
        "palette": ["2eef35", "0047ff"],
    },
    "vv_vh_contrast": {
        "bands": ["VV", "VH", "VV_minus_VH"],
        "min": [-22.0, -28.0, 0.0],
        "max": [0.0, -4.0, 12.0],
    },
}
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DISK_CACHE_PATH = _REPO_ROOT / ".cache" / "sar_tiles.json"
_RASTER_CACHE_ROOT = _REPO_ROOT / ".cache" / "sar_rasters"
_DISK_CACHE_LOADED = False


@dataclass(frozen=True)
class RasterCacheStats:
    root: Path
    tiles: int
    bytes: int


@dataclass(frozen=True)
class SarTileMetrics:
    rendered_cache_hits: int
    local_asset_hits: int
    local_renders: int
    earth_engine_fallbacks: int
    tile_render_latency_ms_total: float
    tile_render_latency_ms_avg: float


_METRICS = {
    "rendered_cache_hits": 0,
    "local_asset_hits": 0,
    "local_renders": 0,
    "earth_engine_fallbacks": 0,
    "tile_render_latency_ms_total": 0.0,
}


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


def _image_and_vis(ee, scene_id: str, composite: str):
    img = ee.Image(f"COPERNICUS/S1_GRD/{scene_id}")
    if composite in {"false_color", "vv_vh_contrast"}:
        diff = img.select("VV").subtract(img.select("VH")).rename("VV_minus_VH")
        img = img.addBands(diff)
    if composite == "water_class":
        img = img.select("VH").lt(-18.0).rename("water_class")
    return img, _COMPOSITES[composite]


def validate_composite(composite: str) -> str:
    if composite not in _COMPOSITES:
        allowed = ", ".join(sorted(_COMPOSITES))
        raise ValueError(f"unknown SAR composite {composite!r}; expected one of: {allowed}")
    return composite


def mint_tile(scene_id: str, composite: str = DEFAULT_COMPOSITE) -> tuple[str, datetime]:
    """One EE round-trip: scene asset -> map id -> tile URL template + expiry."""
    try:
        import ee  # noqa: PLC0415 — optional dependency corner

        composite = validate_composite(composite)
        _ensure_ee_initialized()
        img, vis = _image_and_vis(ee, scene_id, composite)
        mapid = img.getMapId(vis)
        url = str(mapid["tile_fetcher"].url_format)
        # EE does not return an expiry; map ids last ~4 h — advertise 3.5 h.
        return url, datetime.now(UTC) + timedelta(hours=3, minutes=30)
    except GeeUnavailable:
        raise
    except Exception as exc:  # ee import/auth/asset errors — all mean "degrade"
        raise GeeUnavailable(str(exc)) from exc


def _cache_key(rid: str, date: str, scene_id: str, composite: str) -> tuple[str, str, str, str]:
    return (rid, date, scene_id, composite)


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
            parts = key.split("|", 3)
            if len(parts) == 3:
                rid, date, scene_id = parts
                composite = DEFAULT_COMPOSITE
            else:
                rid, date, scene_id, composite = parts
            exp = datetime.fromisoformat(item["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            if exp - _SAFETY > now:
                _CACHE[_cache_key(rid, date, scene_id, composite)] = (str(item["tile_url"]), exp)
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


def get_cached_tile(
    rid: str, date: str, scene_id: str, composite: str = DEFAULT_COMPOSITE
) -> tuple[str, datetime]:
    composite = validate_composite(composite)
    _load_disk_cache()
    key = _cache_key(rid, date, scene_id, composite)
    hit = _CACHE.get(key)
    now = datetime.now(UTC)
    if hit and hit[1] - _SAFETY > now:
        _CACHE.move_to_end(key)
        return hit
    fresh = mint_tile(scene_id, composite)
    _CACHE[key] = fresh
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    _save_disk_cache()
    return fresh


def _raster_path(rid: str, date: str, composite: str, z: int, x: int, y: int) -> Path:
    safe_rid = "".join(ch for ch in rid if ch.isalnum() or ch in "_-")
    safe_date = "".join(ch for ch in date if ch.isalnum() or ch in "_-")
    safe_composite = "".join(ch for ch in composite if ch.isalnum() or ch in "_-")
    return _RASTER_CACHE_ROOT / safe_rid / safe_date / safe_composite / str(z) / str(x) / f"{y}.png"


def get_cached_raster_content(
    rid: str, date: str, composite: str, z: int, x: int, y: int
) -> bytes | None:
    """Return an already-rendered/proxied PNG tile without contacting Earth Engine."""
    composite = validate_composite(composite)
    path = _raster_path(rid, date, composite, z, x, y)
    try:
        return path.read_bytes() if path.exists() else None
    except OSError:
        return None


def put_cached_raster_content(
    rid: str, date: str, composite: str, z: int, x: int, y: int, content: bytes
) -> None:
    """Persist a rendered PNG tile in the shared raster cache."""
    composite = validate_composite(composite)
    path = _raster_path(rid, date, composite, z, x, y)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(content)
        tmp.replace(path)
    except OSError:
        return


def raster_cache_stats(root: Path | None = None) -> RasterCacheStats:
    """Summarise rendered/proxied SAR PNG cache usage."""
    root = root or _RASTER_CACHE_ROOT
    tiles = 0
    size = 0
    if not root.exists():
        return RasterCacheStats(root=root, tiles=0, bytes=0)
    for path in root.rglob("*.png"):
        try:
            stat = path.stat()
        except OSError:
            continue
        tiles += 1
        size += stat.st_size
    return RasterCacheStats(root=root, tiles=tiles, bytes=size)


def cleanup_raster_cache(max_bytes: int, root: Path | None = None) -> RasterCacheStats:
    """Delete oldest cached PNG tiles until the raster cache is within ``max_bytes``."""
    root = root or _RASTER_CACHE_ROOT
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    if not root.exists():
        return RasterCacheStats(root=root, tiles=0, bytes=0)
    entries: list[tuple[float, Path, int]] = []
    total = 0
    tiles = 0
    for path in root.rglob("*.png"):
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, path, stat.st_size))
        total += stat.st_size
        tiles += 1
    for _, path, size in sorted(entries):
        if total <= max_bytes:
            break
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        tiles -= 1
    return RasterCacheStats(root=root, tiles=tiles, bytes=total)


def record_rendered_cache_hit() -> None:
    _METRICS["rendered_cache_hits"] += 1


def record_local_asset_hit() -> None:
    _METRICS["local_asset_hits"] += 1


def record_local_render(latency_ms: float) -> None:
    _METRICS["local_renders"] += 1
    _METRICS["tile_render_latency_ms_total"] += latency_ms


def record_earth_engine_fallback(latency_ms: float) -> None:
    _METRICS["earth_engine_fallbacks"] += 1
    _METRICS["tile_render_latency_ms_total"] += latency_ms


def sar_tile_metrics() -> SarTileMetrics:
    rendered = int(_METRICS["local_renders"] + _METRICS["earth_engine_fallbacks"])
    total_latency = float(_METRICS["tile_render_latency_ms_total"])
    return SarTileMetrics(
        rendered_cache_hits=int(_METRICS["rendered_cache_hits"]),
        local_asset_hits=int(_METRICS["local_asset_hits"]),
        local_renders=int(_METRICS["local_renders"]),
        earth_engine_fallbacks=int(_METRICS["earth_engine_fallbacks"]),
        tile_render_latency_ms_total=total_latency,
        tile_render_latency_ms_avg=total_latency / rendered if rendered else 0.0,
    )


def reset_sar_tile_metrics() -> None:
    for key in _METRICS:
        _METRICS[key] = 0.0 if key.endswith("_total") else 0


def get_cached_raster(
    tile_url: str, rid: str, date: str, composite: str, z: int, x: int, y: int
) -> bytes:
    """Fetch one XYZ tile through the API and persist it for later playback."""
    composite = validate_composite(composite)
    path = _raster_path(rid, date, composite, z, x, y)
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
