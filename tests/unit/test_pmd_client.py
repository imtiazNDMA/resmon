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
    latest_model_time,
    normalize_city_forecast_features,
    normalize_ffd_waterlevel_features,
    normalize_glof_observation_features,
    normalize_lightning_features,
    normalize_monitor_station_features,
    normalize_monsoon_features,
    normalize_nwfc_observation_features,
    normalize_prediction_frames,
    normalize_warning_features,
    parse_json_string,
    pmd_forecast_element,
    pmd_forecast_element_candidates,
    pmd_source,
    summarize_model_time_response,
    thin_prediction_frames,
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


def test_forecast_element_registry_marks_wrfprs_precipitation_as_candidates():
    keys = {candidate.key for candidate in pmd_forecast_element_candidates()}

    assert {
        "pmd_pred_hourtpe",
        "pmd_pred_sixtpe",
        "pmd_pred_twelvetpe",
        "pmd_pred_daytpe",
    } <= keys
    hour = pmd_forecast_element("pmd_pred_hourtpe")
    assert hour.data_type == "WRFPRS"
    assert hour.element == "HOURTPE"
    assert hour.status == "candidate"


def test_summarize_model_time_response_handles_common_shapes_and_sentinels():
    summary = summarize_model_time_response(
        {
            "data": [
                {"model_time": "2026-08-05 00:00", "frames": ["+1h", "+2h"]},
                {"run_time": "2026-08-05 06:00", "frames": [9999, "+8h"]},
            ]
        }
    )

    assert summary == {
        "available": True,
        "row_count": 2,
        "model_times": ["2026-08-05 00:00", "2026-08-05 06:00"],
        "frame_count": 4,
    }


def test_summarize_model_time_response_accepts_string_rows():
    summary = summarize_model_time_response(["2026-08-05 00:00", ""])

    assert summary["available"] is True
    assert summary["row_count"] == 2
    assert summary["model_times"] == ["2026-08-05 00:00"]
    assert summary["frame_count"] is None


def test_latest_model_time_uses_last_available_run():
    assert latest_model_time(["2026-08-05 00:00", "2026-08-05 06:00"]) == "2026-08-05 06:00"
    assert latest_model_time([]) is None


def test_normalize_and_thin_prediction_frames():
    frames = normalize_prediction_frames(
        {
            "frames": [
                {"forecast_time": "+1h", "bounds": "[73,33,74,34]"},
                {"forecast_time": "+2h", "coordinates": "[[73,33],[74,34]]"},
                {"forecast_time": "+3h"},
                {"forecast_time": "+4h"},
            ]
        }
    )

    assert frames[0]["date"] == "+1h"
    assert frames[0]["bounds"] == [73, 33, 74, 34]
    assert frames[1]["coordinates"] == [[73, 33], [74, 34]]
    assert [frame["date"] for frame in thin_prediction_frames(frames, 2)] == ["+1h", "+2h"]


def test_normalize_monitor_station_features_accepts_geojson_and_cleans_values():
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [73.1, 33.7]},
                "properties": {
                    "station_id": "1",
                    "code": "OPIS",
                    "name": "Islamabad",
                    "station_type": "synop",
                    "date_time": "2026-08-05 10:00:00",
                    "temperature": 31.5,
                    "rain_24h": 9999.0,
                    "status": "true",
                    "warn_rain": "yellow",
                },
            }
        ],
    }

    normalized = normalize_monitor_station_features(payload, cache_status="fetched")
    feature = normalized["features"][0]

    assert feature["geometry"] == {"type": "Point", "coordinates": [73.1, 33.7]}
    assert feature["properties"]["temperature_c"] == 31.5
    assert feature["properties"]["rain_24h_mm"] is None
    assert feature["properties"]["status"] is True
    assert feature["properties"]["source"] == "PMD Monitor"


def test_normalize_monitor_station_features_accepts_raw_rows_with_lat_lon():
    normalized = normalize_monitor_station_features(
        [{"lat": "33.7", "lon": "73.1", "temp": "29.5", "pre24": "12.0"}],
        cache_status="stale",
    )

    props = normalized["features"][0]["properties"]
    assert props["temperature_c"] == 29.5
    assert props["rain_24h_mm"] == 12.0
    assert props["stale"] is True


def test_normalize_nwfc_observation_features_preserves_weather_fields():
    normalized = normalize_nwfc_observation_features(
        {
            "data": [
                {
                    "latitude": "34.0",
                    "longitude": "72.5",
                    "station_code": "NW01",
                    "station_name": "Peshawar",
                    "valid_time": "2026-08-05T06:00:00+05:00",
                    "weather_text": "Cloudy",
                    "icon": "cloudy.png",
                    "temp": "28.1",
                    "pre24": 9999,
                }
            ]
        },
        cache_status="fetched",
    )

    feature = normalized["features"][0]
    assert feature["geometry"] == {"type": "Point", "coordinates": [72.5, 34.0]}
    props = feature["properties"]
    assert props["code"] == "NW01"
    assert props["weather_text"] == "Cloudy"
    assert props["weather_icon"] == "cloudy.png"
    assert props["temperature_c"] == 28.1
    assert props["rain_24h_mm"] is None
    assert props["source"] == "PMD NWFC"


def test_normalize_glof_observation_features_cleans_telemetry():
    normalized = normalize_glof_observation_features(
        [
            {
                "lat": "35.9",
                "lon": "74.3",
                "station_id": "glof-1",
                "station_name": "Hunza GLOF",
                "last_update": "2026-08-05T08:00:00+05:00",
                "connectivity": "online",
                "alert_level": "Watch",
                "rainfall": "9.5",
                "flow": 2147483.75,
                "water_level": "2.1",
                "temp": "6.3",
            }
        ],
        cache_status="stale",
    )

    feature = normalized["features"][0]
    assert feature["geometry"] == {"type": "Point", "coordinates": [74.3, 35.9]}
    props = feature["properties"]
    assert props["station_id"] == "glof-1"
    assert props["connected"] is True
    assert props["alert_level"] == "Watch"
    assert props["rainfall_mm"] == 9.5
    assert props["flow_cms"] is None
    assert props["water_level_m"] == 2.1
    assert props["source"] == "PMD Monitor GLOF"
    assert props["stale"] is True


def test_normalize_lightning_features_keeps_window_and_cleans_current():
    normalized = normalize_lightning_features(
        {
            "data": [
                {
                    "lat": "33.6",
                    "lon": "73.0",
                    "strike_id": "l-1",
                    "timestamp": "2026-08-05T09:00:00+05:00",
                    "polarity": "negative",
                    "peak_current": 9999,
                    "strokes": "2",
                }
            ]
        },
        hours=12,
        cache_status="fetched",
    )

    feature = normalized["features"][0]
    assert feature["geometry"] == {"type": "Point", "coordinates": [73.0, 33.6]}
    props = feature["properties"]
    assert props["strike_id"] == "l-1"
    assert props["window_hours"] == 12
    assert props["peak_current_ka"] is None
    assert props["multiplicity"] == 2.0
    assert props["source"] == "PMD Monitor Lightning"


def test_normalize_ffd_waterlevel_features_parses_gauge_json():
    normalized = normalize_ffd_waterlevel_features(
        {
            "rows": [
                {
                    "latitude": "31.4",
                    "longitude": "73.1",
                    "site_id": "ffd-1",
                    "site_name": "River Chenab Gauge",
                    "river_name": "Chenab",
                    "last_update": "2026-08-05T10:00:00+05:00",
                    "water_level": "3.4",
                    "discharge": "12500",
                    "status": "Low Flood",
                    "gauges": '[{"name":"upstream","level":9999},{"name":"main","level":3.4}]',
                }
            ]
        },
        cache_status="fetched",
    )

    feature = normalized["features"][0]
    assert feature["geometry"] == {"type": "Point", "coordinates": [73.1, 31.4]}
    props = feature["properties"]
    assert props["station_id"] == "ffd-1"
    assert props["river"] == "Chenab"
    assert props["water_level_m"] == 3.4
    assert props["discharge_cusecs"] == 12500.0
    assert props["status"] == "Low Flood"
    assert props["gauges"] == [{"name": "upstream", "level": None}, {"name": "main", "level": 3.4}]
    assert props["source"] == "FFD Flood Forecasting Division"


def test_normalize_warning_features_parses_geometry_and_fields():
    normalized = normalize_warning_features(
        [
            {
                "geometry": '{"type":"Polygon","coordinates":[[[73,33],[74,33],[74,34],[73,33]]]}',
                "warning_id": "w-1",
                "severity": "Warning",
                "data_type": "Heavy Rain",
                "model": "wrf",
                "forecast_time": "2026-08-05T12:00:00+05:00",
                "issued_at": "2026-08-05T06:00:00+05:00",
                "message": "Heavy rainfall expected",
                "district": "Rawalpindi",
            }
        ],
        cache_status="fetched",
    )

    feature = normalized["features"][0]
    assert feature["geometry"]["type"] == "Polygon"
    props = feature["properties"]
    assert props["warning_id"] == "w-1"
    assert props["hazard"] == "Heavy Rain"
    assert props["area_name"] == "Rawalpindi"
    assert props["source"] == "PMD Monitor"


def test_normalize_monsoon_features_parses_forecast_json():
    normalized = normalize_monsoon_features(
        [
            {
                "lat": "30.2",
                "lon": "71.5",
                "id": "m-1",
                "level": "Watch",
                "data_type": "Monsoon Rain",
                "date_time": "2026-08-05T06:00:00+05:00",
                "fc": '[{"period":"24h","rain_mm":9999},{"period":"48h","rain_mm":22}]',
            }
        ],
        cache_status="stale",
    )

    props = normalized["features"][0]["properties"]
    assert props["warning_id"] == "m-1"
    assert props["forecast"] == [
        {"period": "24h", "rain_mm": None},
        {"period": "48h", "rain_mm": 22},
    ]
    assert props["stale"] is True


def test_normalize_city_forecast_features_parses_forecast_array():
    normalized = normalize_city_forecast_features(
        [
            {
                "lat": "33.7",
                "lon": "73.1",
                "city_id": "isb",
                "city_name": "Islamabad",
                "date_time": "2026-08-05T06:00:00+05:00",
                "weather_text": "Cloudy",
                "temp": "31",
                "fc": '[{"t":"+3h","temp":32},{"t":"+6h","temp":9999}]',
            }
        ],
        cache_status="fetched",
    )

    props = normalized["features"][0]["properties"]
    assert props["city_id"] == "isb"
    assert props["name"] == "Islamabad"
    assert props["forecast"] == [{"t": "+3h", "temp": 32}, {"t": "+6h", "temp": None}]


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
