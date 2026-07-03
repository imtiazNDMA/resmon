"""Live Sentinel-1 tile URLs for the map (dashboard spec endpoint 2).

The only optional-GEE corner of the API: everything else runs credential-free.
EE map ids expire (~4 h), so mints are cached per (reservoir, date) with the
expiry advertised to clients, minus a safety margin. GeeUnavailable -> the route
503s and the frontend falls back to basemap + AOI outline (honesty state, spec).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

from core.config import get_settings

_CACHE: dict[tuple[str, str], tuple[str, datetime]] = {}
_SAFETY = timedelta(minutes=10)
_VIS = {"bands": ["VH"], "min": -25.0, "max": -5.0}  # dark-water SAR styling


class GeeUnavailable(RuntimeError):
    """GEE credentials missing or initialisation failed — degrade, don't crash."""


def mint_tile(scene_id: str) -> tuple[str, datetime]:
    """One EE round-trip: scene asset -> map id -> tile URL template + expiry."""
    try:
        import ee  # noqa: PLC0415 — optional dependency corner

        key_file = get_settings().gee_sa_key_file or "geeservice.json"
        if not os.path.exists(key_file):
            raise GeeUnavailable(f"no GEE key file at {key_file}")
        with open(key_file, encoding="utf-8") as fh:
            info = json.load(fh)
        ee.Initialize(
            ee.ServiceAccountCredentials(info["client_email"], key_file),
            project=info["project_id"],
        )
        img = ee.Image(f"COPERNICUS/S1_GRD/{scene_id}")
        mapid = img.getMapId(_VIS)
        url = str(mapid["tile_fetcher"].url_format)
        # EE does not return an expiry; map ids last ~4 h — advertise 3.5 h.
        return url, datetime.now(UTC) + timedelta(hours=3, minutes=30)
    except GeeUnavailable:
        raise
    except Exception as exc:  # ee import/auth/asset errors — all mean "degrade"
        raise GeeUnavailable(str(exc)) from exc


def get_cached_tile(rid: str, date: str, scene_id: str) -> tuple[str, datetime]:
    key = (rid, date)
    hit = _CACHE.get(key)
    now = datetime.now(UTC)
    if hit and hit[1] - _SAFETY > now:
        return hit
    fresh = mint_tile(scene_id)
    _CACHE[key] = fresh
    return fresh
