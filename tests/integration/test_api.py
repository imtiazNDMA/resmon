"""API endpoint tests via TestClient, with get_db overridden to the test session so the
HTTP layer reads the uncommitted pipeline output in this transaction.
"""

from __future__ import annotations

import pytest
from api.db import get_db
from api.main import app
from data_engineering.ingest import ingest_bulletins
from data_engineering.pipeline import DEFAULT_CSV
from data_engineering.seed import seed_reservoirs
from fastapi.testclient import TestClient
from ml.forecasting import run_forecasting
from ml.release import run_release_risk


@pytest.fixture
def client(session):
    seed_reservoirs(session)
    ingest_bulletins(session, DEFAULT_CSV)
    run_forecasting(session, version="fc_api")
    run_release_risk(session)

    def _override():
        yield session

    app.dependency_overrides[get_db] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_reservoir_catalogue_and_detail(client):
    r = client.get("/reservoirs")
    assert r.status_code == 200 and len(r.json()) == 3
    # numeric columns must be JSON numbers, not Decimal strings (the frontend calls .toFixed)
    assert isinstance(r.json()[0]["frl_m"], (int, float))
    assert isinstance(r.json()[0]["live_capacity_bcm"], (int, float))
    assert client.get("/reservoirs/pong").status_code == 200
    assert client.get("/reservoirs/does_not_exist").status_code == 404


def test_status_and_timeseries(client):
    status = client.get("/reservoirs/pong/status").json()
    assert "risk_level" in status and "pct_filled" in status
    ts = client.get("/reservoirs/pong/timeseries?limit=10").json()
    assert 0 < len(ts) <= 10
    assert isinstance(ts[0]["pct_filled"], (int, float))  # JSON number for the trend chart


def test_forecast_and_release_risk(client):
    fc = client.get("/reservoirs/pong/forecast").json()
    assert fc["horizon"] == 14 and len(fc["points"]) == 14
    assert all("interval_low" in p and "interval_high" in p for p in fc["points"])

    fleet = client.get("/release-risk").json()
    assert len(fleet) == 3
    assert all(x["risk_level"] in ("Low", "Watch", "Warning", "Imminent") for x in fleet)


def test_geojson_feature_collection(client):
    gj = client.get("/geojson/reservoirs").json()
    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == 3
    f = gj["features"][0]
    assert f["geometry"]["type"] == "Point"
    assert "risk_level" in f["properties"]


def test_geojson_layers(client):
    # AOI polygons exist after seeding (placeholder until GEE populates real ones).
    aoi = client.get("/geojson/aoi").json()
    assert aoi["type"] == "FeatureCollection"
    assert len(aoi["features"]) == 3
    assert aoi["features"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")
    # Catchment / water-extent layers are valid collections (empty until GEE populates them).
    for path in ("/geojson/catchment", "/geojson/water-extent"):
        layer = client.get(path).json()
        assert layer["type"] == "FeatureCollection"


def test_openapi_published(client):
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "Reservoir Monitoring & Analytics API"
    assert "/reservoirs" in schema["paths"]
    # D5: routes declare typed response models — the contract is no longer `{}`.
    ok = schema["paths"]["/reservoirs"]["get"]["responses"]["200"]
    assert ok["content"]["application/json"]["schema"]["items"]["$ref"].endswith("ReservoirSummary")
