"""Server-side PMD Monitor client foundation.

This module owns PMD Monitor authentication, upstream caching, stale fallback, and
basic data cleaning. It deliberately does not define public API routes yet; Phase 8C
routes should depend on this seam and keep network behavior out of repositories.
"""

from __future__ import annotations

import json
import math
import ssl
import threading
import time
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from typing import Any

import requests
from core.config import get_settings
from requests.adapters import HTTPAdapter

SENTINEL_VALUES = {-9999.0, -999.0, 999.0, 9999.0}
INT32_SENTINEL_MIN_ABS = 2_000_000.0


class PmdConfigError(RuntimeError):
    """PMD Monitor is not configured for live upstream calls."""


class PmdUpstreamError(RuntimeError):
    """PMD Monitor upstream request failed."""


@dataclass(frozen=True)
class PmdCacheEntry:
    value: Any
    expires_at: float
    stored_at: float


@dataclass(frozen=True)
class PmdCacheResult:
    value: Any
    cache_status: str  # fresh | fetched | stale


@dataclass(frozen=True)
class PmdSource:
    key: str
    source_name: str
    upstream_path: str
    ttl_seconds: int
    geometry_type: str
    limitations: str


PMD_SOURCES: dict[str, PmdSource] = {
    "monitor_stations": PmdSource(
        key="monitor_stations",
        source_name="PMD Monitor",
        upstream_path="api/gts_warnning_data",
        ttl_seconds=300,
        geometry_type="Point",
        limitations="Live station observations; station coverage and sensor availability vary.",
    ),
    "monitor_warnings": PmdSource(
        key="monitor_warnings",
        source_name="PMD Monitor",
        upstream_path="api/get_warning_id + api/warning_area",
        ttl_seconds=120,
        geometry_type="Polygon/MultiPolygon",
        limitations="Active warning polygons only; empty response can mean no active warnings.",
    ),
    "monitor_monsoon": PmdSource(
        key="monitor_monsoon",
        source_name="PMD Monitor",
        upstream_path="api/monsoon_warnning_data",
        ttl_seconds=300,
        geometry_type="Point/Polygon",
        limitations="Monsoon-season warnings; schema may include text-only rows without geometry.",
    ),
    "monitor_glof_observations": PmdSource(
        key="monitor_glof_observations",
        source_name="PMD Monitor GLOF",
        upstream_path="api/glofStationObsData",
        ttl_seconds=120,
        geometry_type="Point",
        limitations=(
            "GLOF station telemetry requires sentinel-value filtering and connectivity checks."
        ),
    ),
    "monitor_lightning": PmdSource(
        key="monitor_lightning",
        source_name="PMD Monitor Lightning",
        upstream_path="api/radar/thunder/lightHis",
        ttl_seconds=180,
        geometry_type="Point",
        limitations="Recent strike window only; zero strikes is a normal no-data condition.",
    ),
    "monitor_city_forecast": PmdSource(
        key="monitor_city_forecast",
        source_name="PMD Monitor City Forecast",
        upstream_path="api/getBandRCityForecast12",
        ttl_seconds=1800,
        geometry_type="Point",
        limitations=(
            "City forecast features include nested forecast arrays from upstream JSON strings."
        ),
    ),
    "nwfc_observations": PmdSource(
        key="nwfc_observations",
        source_name="PMD NWFC",
        upstream_path="api/pmd/nwfc/observations/",
        ttl_seconds=300,
        geometry_type="Point",
        limitations="NWFC scrape; useful as a station-observation cross-check.",
    ),
    "ffd_waterlevels": PmdSource(
        key="ffd_waterlevels",
        source_name="FFD Flood Forecasting Division",
        upstream_path="get-ffd-waterlevels/",
        ttl_seconds=300,
        geometry_type="Point",
        limitations="Current river-gauge snapshot; history must be sampled/persisted separately.",
    ),
}

EXCLUDED_PMD_ENDPOINTS = frozenset(
    {
        "api/pmd/monitor/debug/",
        "api/pmd/nwfc/debug-station/",
        "raw_upstream_probe",
    }
)


class PmdLegacyTLSAdapter(HTTPAdapter):
    """Requests adapter for PMD Monitor's self-signed/legacy TLS host only."""

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
        except Exception:
            pass
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1
        except Exception:
            pass
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


def pmd_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.pmd_monitor_url and settings.pmd_monitor_user and settings.pmd_monitor_pass
    )


def pmd_source(key: str) -> PmdSource:
    return PMD_SOURCES[key]


def clean_pmd_value(value: Any) -> Any:
    """Convert PMD sentinel/fault numeric values to ``None`` recursively."""
    if isinstance(value, dict):
        return {key: clean_pmd_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_pmd_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(clean_pmd_value(item) for item in value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        number = float(value)
        if not math.isfinite(number):
            return None
        if number in SENTINEL_VALUES or abs(number) >= INT32_SENTINEL_MIN_ABS:
            return None
    return value


def parse_json_string(value: Any) -> Any:
    """Parse nested JSON-as-string PMD fields, leaving non-JSON strings unchanged."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def extract_jwt(payload: Any) -> str | None:
    """Find a bearer token across common PMD/vendor login response shapes."""
    if not isinstance(payload, dict):
        return None
    for key in ("token", "access_token", "jwt", "jwtToken", "accessToken", "id_token"):
        value = payload.get(key)
        if isinstance(value, str) and len(value) > 20:
            return value
    data = payload.get("data")
    if isinstance(data, dict):
        return extract_jwt(data)
    if isinstance(data, str) and len(data) > 20:
        return data
    return None


class PmdMonitorClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout_seconds: int = 12,
        session_factory: Callable[[], requests.Session] | None = None,
        now: Callable[[], float] = time.monotonic,
        cache: MutableMapping[str, PmdCacheEntry] | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.pmd_monitor_url or "").rstrip("/")
        self.username = username if username is not None else settings.pmd_monitor_user
        self.password = password if password is not None else settings.pmd_monitor_pass
        self.timeout_seconds = timeout_seconds
        self._session_factory = session_factory or self._make_session
        self._now = now
        self._cache: MutableMapping[str, PmdCacheEntry] = cache if cache is not None else {}
        self._session: requests.Session | None = None
        self._session_expires_at = 0.0
        self._lock = threading.Lock()

    def configured(self) -> bool:
        return bool(self.base_url and self.username and self.password)

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request_json("GET", path, params=params)

    def post_json(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        return self._request_json("POST", path, payload=payload)

    def get_bytes(self, path: str, params: dict[str, Any] | None = None) -> bytes:
        response = self._request("GET", path, params=params)
        return response.content

    def cached(
        self,
        key: str,
        ttl_seconds: int,
        fetch: Callable[[], Any],
        *,
        fallback_key: str | None = None,
    ) -> PmdCacheResult:
        now = self._now()
        entry = self._cache.get(key)
        if entry is not None and entry.expires_at > now:
            return PmdCacheResult(entry.value, "fresh")
        try:
            value = fetch()
        except Exception:
            stale_key = fallback_key or key
            stale = self._cache.get(stale_key)
            if stale is not None:
                return PmdCacheResult(stale.value, "stale")
            raise
        entry = PmdCacheEntry(value=value, expires_at=now + ttl_seconds, stored_at=now)
        self._cache[key] = entry
        if fallback_key is not None:
            self._cache[fallback_key] = PmdCacheEntry(
                value=value, expires_at=now + ttl_seconds * 6, stored_at=now
            )
        return PmdCacheResult(value, "fetched")

    def _make_session(self) -> requests.Session:
        requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
        session = requests.Session()
        session.mount("https://", PmdLegacyTLSAdapter())
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/html, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"{self.base_url}/",
            }
        )
        return session

    def _get_session(self) -> requests.Session:
        if not self.configured():
            raise PmdConfigError("PMD Monitor credentials are not configured")
        now = self._now()
        if self._session is not None and self._session_expires_at > now:
            return self._session
        with self._lock:
            if self._session is not None and self._session_expires_at > now:
                return self._session
            session = self._session_factory()
            self._login(session)
            self._session = session
            self._session_expires_at = now + 3600
            return session

    def _invalidate_session(self) -> None:
        with self._lock:
            self._session = None
            self._session_expires_at = 0.0

    def _login(self, session: requests.Session) -> None:
        response = session.post(
            f"{self.base_url}/user/login",
            json={"username": self.username, "password": self.password},
            timeout=self.timeout_seconds,
            verify=False,
            allow_redirects=False,
        )
        if response.status_code not in (200, 201):
            raise PmdUpstreamError(f"PMD Monitor login failed: HTTP {response.status_code}")
        token = extract_jwt(response.json())
        if token is None:
            raise PmdUpstreamError("PMD Monitor login did not return a bearer token")
        session.headers["Authorization"] = f"Bearer {token}"

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        response = self._request(method, path, params=params, payload=payload)
        try:
            return clean_pmd_value(response.json())
        except ValueError as exc:
            raise PmdUpstreamError(f"PMD Monitor returned non-JSON for {path}") from exc

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        for attempt in range(2):
            session = self._get_session()
            response = session.request(
                method,
                url,
                params=params,
                json=payload,
                timeout=self.timeout_seconds,
                verify=False,
            )
            if response.status_code in (401, 403) and attempt == 0:
                self._invalidate_session()
                continue
            if response.status_code >= 400:
                raise PmdUpstreamError(f"PMD Monitor request failed: HTTP {response.status_code}")
            return response
        raise PmdUpstreamError(f"PMD Monitor authentication failed for {path}")
