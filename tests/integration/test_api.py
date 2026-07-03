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
from sqlalchemy import text


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


@pytest.fixture
def seeded_observation_rows(client, session):
    """Two real (non-stub) SAR observations for gobind_sagar, mirroring the Task-1 loader."""
    for d, area, conf, sid in (
        ("2020-01-05", 120.5, 0.92, "S1A_TEST_0001"),
        ("2020-01-29", 118.2, 0.91, "S1A_TEST_0003"),
    ):
        session.execute(
            text(
                """
                INSERT INTO observation
                    (reservoir_id, acquisition_date, surface_area, area_confidence,
                     water_mask_ref, extraction_method, extraction_version, scene_ids,
                     orbit_relative, pass_direction, aoi_version, layover_shadow_fraction,
                     processing_params)
                VALUES
                    ('gobind_sagar', :d, :area, :conf, :ref, 'otsu_vh', 'v1',
                     ARRAY[:sid], 27, 'ASC', 'v1', 0, CAST('{}' AS jsonb))
                ON CONFLICT (reservoir_id, acquisition_date) DO UPDATE SET
                    surface_area = EXCLUDED.surface_area,
                    extraction_method = EXCLUDED.extraction_method,
                    scene_ids = EXCLUDED.scene_ids
                """
            ),
            {"d": d, "area": area, "conf": conf, "ref": f"backfill://{sid}", "sid": sid},
        )


def test_acquisitions_endpoint_serves_real_series(client, seeded_observation_rows):
    r = client.get("/reservoirs/gobind_sagar/acquisitions")
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 2
    first = body[0]
    assert set(first) == {"date", "area_km2", "confidence"}
    assert isinstance(first["area_km2"], (int, float))
    dates = [row["date"] for row in body]
    assert dates == sorted(dates)


def test_acquisitions_unknown_reservoir_404(client):
    assert client.get("/reservoirs/nope/acquisitions").status_code == 404


def test_rainfall_endpoint_empty_is_honest(client):
    r = client.get("/reservoirs/gobind_sagar/rainfall?window=30")
    assert r.status_code == 200
    assert r.json() == []  # no forcing rows seeded -> honest empty, not fake zeros


def test_rainfall_unknown_reservoir_404(client):
    assert client.get("/reservoirs/nope/rainfall").status_code == 404


def test_openapi_published(client):
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "Reservoir Monitoring & Analytics API"
    assert "/reservoirs" in schema["paths"]
    # D5: routes declare typed response models — the contract is no longer `{}`.
    ok = schema["paths"]["/reservoirs"]["get"]["responses"]["200"]
    assert ok["content"]["application/json"]["schema"]["items"]["$ref"].endswith("ReservoirSummary")
