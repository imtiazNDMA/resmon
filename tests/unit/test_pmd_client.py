from __future__ import annotations

import pytest
from api.pmd_client import (
    EXCLUDED_PMD_ENDPOINTS,
    PMD_SOURCES,
    PmdCacheEntry,
    PmdConfigError,
    PmdMonitorClient,
    clean_pmd_value,
    extract_jwt,
    parse_json_string,
    pmd_source,
)


class FakeResponse:
    def __init__(self, status_code: int, payload=None, content: bytes = b"") -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = content

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.headers: dict[str, str] = {}
        self.posts: list[dict] = []
        self.requests: list[dict] = []

    def post(self, url, **kwargs):
        self.posts.append({"url": url, **kwargs})
        return FakeResponse(200, {"token": "x" * 32})

    def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


def test_extract_jwt_checks_common_and_nested_shapes():
    assert extract_jwt({"token": "a" * 32}) == "a" * 32
    assert extract_jwt({"data": {"accessToken": "b" * 32}}) == "b" * 32
    assert extract_jwt({"token": "short"}) is None
    assert extract_jwt([]) is None


def test_clean_pmd_value_converts_fault_sentinels_recursively():
    payload = {
        "ok": 12.5,
        "missing": 9999.0,
        "fault": 2147483.75,
        "nested": [{"rain": -9999, "text": "9999"}],
    }

    assert clean_pmd_value(payload) == {
        "ok": 12.5,
        "missing": None,
        "fault": None,
        "nested": [{"rain": None, "text": "9999"}],
    }


def test_parse_json_string_only_parses_json_like_strings():
    assert parse_json_string('[{"type":"INFLOW"}]') == [{"type": "INFLOW"}]
    assert parse_json_string('{"pre24":9999}') == {"pre24": 9999}
    assert parse_json_string("Rain") == "Rain"
    assert parse_json_string("[broken") == "[broken"


def test_source_registry_tracks_ttls_attribution_and_debug_exclusions():
    stations = pmd_source("monitor_stations")
    assert stations.source_name == "PMD Monitor"
    assert stations.ttl_seconds == 300
    assert stations.geometry_type == "Point"
    assert "monitor_debug" not in PMD_SOURCES
    assert "api/pmd/monitor/debug/" in EXCLUDED_PMD_ENDPOINTS


def test_cached_returns_fresh_then_stale_on_fetch_failure():
    now = 1000.0
    cache: dict[str, PmdCacheEntry] = {}
    client = PmdMonitorClient(
        base_url="https://example.test",
        username="u",
        password="p",
        now=lambda: now,
        cache=cache,
    )
    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        return {"value": calls}

    first = client.cached("key", 60, fetch, fallback_key="fallback")
    assert first.cache_status == "fetched"
    assert first.value == {"value": 1}

    second = client.cached("key", 60, lambda: pytest.fail("should not fetch"))
    assert second.cache_status == "fresh"
    assert second.value == {"value": 1}

    now = 2000.0
    stale = client.cached(
        "key",
        60,
        lambda: (_ for _ in ()).throw(RuntimeError("down")),
        fallback_key="fallback",
    )
    assert stale.cache_status == "stale"
    assert stale.value == {"value": 1}


def test_client_raises_when_not_configured():
    client = PmdMonitorClient(base_url="", username="", password="")

    with pytest.raises(PmdConfigError):
        client.get_json("api/gts_warnning_data")


def test_get_json_logs_in_and_retries_once_after_unauthorized():
    sessions = [FakeSession([FakeResponse(401, {}), FakeResponse(200, {"rain": 9999.0})])]
    client = PmdMonitorClient(
        base_url="https://example.test",
        username="PMD",
        password="secret",
        session_factory=lambda: sessions[0],
    )

    assert client.get_json("api/gts_warnning_data") == {"rain": None}
    assert sessions[0].headers["Authorization"] == "Bearer " + "x" * 32
    assert len(sessions[0].posts) == 2
    assert len(sessions[0].requests) == 2


def test_get_bytes_keeps_binary_payload_unparsed():
    session = FakeSession([FakeResponse(200, {"ignored": True}, content=b"tiff-bytes")])
    client = PmdMonitorClient(
        base_url="https://example.test",
        username="PMD",
        password="secret",
        session_factory=lambda: session,
    )

    assert client.get_bytes("static/model.tif") == b"tiff-bytes"
