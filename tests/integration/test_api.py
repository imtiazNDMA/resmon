"""API endpoint tests via TestClient, with get_db overridden to the test session so the
HTTP layer reads the uncommitted pipeline output in this transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from api.db import get_db
from api.main import app
from api.sar_assets import SarAsset, upsert_asset
from data_engineering.ingest import ingest_bulletins
from data_engineering.pipeline import DEFAULT_CSV
from data_engineering.seed import seed_reservoirs
from fastapi.testclient import TestClient
from ml.forecasting import run_forecasting
from ml.release import run_release_risk
from sqlalchemy import text

from api import gee_tiles


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


def test_reservoir_catalogue_ignores_incomplete_reservoir_metadata(client, session):
    session.execute(
        text(
            """
            INSERT INTO reservoir
              (reservoir_id, name, basin, dam_point, frl_m, live_capacity_bcm,
               aoi_geom, aoi_version, orbit_relative, pass_direction, release_thresholds)
            VALUES
              ('incomplete', 'Incomplete', 'Chenab', ST_GeomFromText('POINT(75 33)', 4326),
               NULL, NULL,
               ST_GeomFromText(
                 'MULTIPOLYGON(((75 33,75.1 33,75.1 33.1,75 33.1,75 33)))', 4326),
               'v1', 12, 'ASC', '{}'::jsonb)
            """
        )
    )

    catalogue = client.get("/reservoirs")
    assert catalogue.status_code == 200
    assert {r["reservoir_id"] for r in catalogue.json()} == {"gobind_sagar", "pong", "thein"}

    markers = client.get("/geojson/reservoirs")
    assert markers.status_code == 200
    assert {f["properties"]["reservoir_id"] for f in markers.json()["features"]} == {
        "gobind_sagar",
        "pong",
        "thein",
    }


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
    districts = client.get("/geojson/districts").json()
    assert districts["type"] == "FeatureCollection"
    assert len(districts["features"]) > 0
    assert districts["features"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")


@pytest.fixture
def seeded_observation_rows(client, session):
    """Two real SAR observations for gobind_sagar (mirroring the Task-1 loader) plus one
    synthetic-provenance row (C5: scene_ids = ['synthetic']) that every serving path
    must exclude — the demo bootstrap stamps such rows with the real extractor name."""
    for d, area, conf, sid in (
        ("2020-01-05", 120.5, 0.92, "S1A_TEST_0001"),
        ("2020-01-29", 118.2, 0.91, "S1A_TEST_0003"),
        ("2026-01-01", 999.0, 0.80, "synthetic"),
    ):
        derived_volume = area / 100
        derived_level = 400 + area / 10
        session.execute(
            text(
                """
                INSERT INTO observation
                    (reservoir_id, acquisition_date, surface_area, area_confidence,
                     derived_volume, derived_level,
                     water_mask_ref, extraction_method, extraction_version, scene_ids,
                     orbit_relative, pass_direction, aoi_version, layover_shadow_fraction,
                     processing_params)
                VALUES
                    ('gobind_sagar', :d, :area, :conf, :derived_volume, :derived_level,
                     :ref, 'otsu_vh', 'v1',
                     ARRAY[:sid], 27, 'ASC', 'v1', 0, CAST('{}' AS jsonb))
                ON CONFLICT (reservoir_id, acquisition_date) DO UPDATE SET
                    surface_area = EXCLUDED.surface_area,
                    derived_volume = EXCLUDED.derived_volume,
                    derived_level = EXCLUDED.derived_level,
                    extraction_method = EXCLUDED.extraction_method,
                    scene_ids = EXCLUDED.scene_ids
                """
            ),
            {
                "d": d,
                "area": area,
                "conf": conf,
                "derived_volume": derived_volume,
                "derived_level": derived_level,
                "ref": f"backfill://{sid}",
                "sid": sid,
            },
        )


def test_acquisitions_endpoint_serves_real_series(client, seeded_observation_rows):
    r = client.get("/reservoirs/gobind_sagar/acquisitions")
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 2
    first = body[0]
    assert set(first) == {
        "date",
        "historical_date",
        "area_km2",
        "confidence",
        "live_storage_bcm",
        "level_m",
        "pct_filled",
        "surface_area_correlation",
        "is_extrapolated",
    }
    assert isinstance(first["area_km2"], (int, float))
    # The fixture observations predate the historical bulletin corpus, so no
    # predicted curve values may leak into this ground-truth-backed endpoint.
    assert first["historical_date"] is None
    assert first["live_storage_bcm"] is None
    assert first["level_m"] is None
    assert first["pct_filled"] is None
    assert first["surface_area_correlation"] is None
    assert isinstance(first["is_extrapolated"], bool)
    dates = [row["date"] for row in body]
    assert dates == sorted(dates)
    # C5 provenance: synthetic rows never reach the timeline, even with a real
    # extractor name — a fake area on the dashboard is a lie about the reservoir.
    assert "2026-01-01" not in dates


def test_sar_tiles_reports_local_source_without_minting_gee(
    client, seeded_observation_rows, monkeypatch, tmp_path
):
    vh = tmp_path / "vh.tif"
    vh.write_bytes(b"placeholder")

    def fake_find_asset(reservoir_id: str, acquisition_date: str, composite: str):
        assert (reservoir_id, acquisition_date, composite) == ("gobind_sagar", "2020-01-05", "vh")
        return SarAsset(
            reservoir_id=reservoir_id,
            acquisition_date=acquisition_date,
            scene_id="S1A_TEST_0001",
            vv_path=None,
            vh_path=vh,
            water_mask_path=None,
            bounds=None,
            min_zoom=8,
            max_zoom=14,
            status="ready",
        )

    def fail_get_cached_tile(*args, **kwargs):
        raise AssertionError("Earth Engine should not be minted for cataloged local assets")

    monkeypatch.setattr("api.routes.sar_assets.find_asset", fake_find_asset)
    monkeypatch.setattr("api.routes.gee_tiles.get_cached_tile", fail_get_cached_tile)

    r = client.get("/reservoirs/gobind_sagar/sar-tiles?date=2020-01-05&composite=vh")

    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "local"
    assert body["composite"] == "vh"
    assert body["tile_url"].endswith("?composite=vh")


def test_sar_tiles_reports_earth_engine_source_when_local_asset_missing(
    client, seeded_observation_rows, monkeypatch
):
    monkeypatch.setattr("api.routes.sar_assets.find_asset", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "api.routes.gee_tiles.get_cached_tile",
        lambda *args, **kwargs: ("https://tiles/{z}/{x}/{y}", datetime(2030, 1, 1, tzinfo=UTC)),
    )

    r = client.get("/reservoirs/gobind_sagar/sar-tiles?date=2020-01-05&composite=vh")

    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "earth_engine"
    assert body["composite"] == "vh"


def test_sar_tiles_rejects_invalid_composite(client, seeded_observation_rows):
    r = client.get("/reservoirs/gobind_sagar/sar-tiles?date=2020-01-05&composite=bogus")

    assert r.status_code == 422


def test_sar_assets_manifest_endpoint_lists_local_coverage(
    client, seeded_observation_rows, monkeypatch, tmp_path
):
    vh = tmp_path / "vh.tif"
    vh.write_bytes(b"placeholder")
    catalog = tmp_path / "catalog.sqlite"
    upsert_asset(
        SarAsset(
            reservoir_id="gobind_sagar",
            acquisition_date="2020-01-05",
            scene_id="S1A_TEST_0001",
            vv_path=None,
            vh_path=vh,
            water_mask_path=None,
            bounds=(74.0, 31.0, 76.0, 33.0),
            min_zoom=8,
            max_zoom=14,
            status="ready",
        ),
        catalog,
    )
    monkeypatch.setattr("api.routes.sar_assets._CATALOG_PATH", catalog)

    r = client.get("/reservoirs/gobind_sagar/sar-assets")

    assert r.status_code == 200
    body = r.json()
    assert body == [
        {
            "reservoir_id": "gobind_sagar",
            "acquisition_date": "2020-01-05",
            "scene_id": "S1A_TEST_0001",
            "composites": ["vh"],
            "bounds": [74.0, 31.0, 76.0, 33.0],
            "min_zoom": 8,
            "max_zoom": 14,
        }
    ]


def test_sar_tile_raster_serves_png_cache_before_minting_gee(
    client, seeded_observation_rows, monkeypatch, tmp_path
):
    monkeypatch.setattr(gee_tiles, "_RASTER_CACHE_ROOT", tmp_path / "rasters")
    path = gee_tiles._raster_path("gobind_sagar", "2020-01-05", "vh", 8, 10, 20)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"cached-png")

    def fail_get_cached_tile(*args, **kwargs):
        raise AssertionError("Earth Engine should not be minted for cached PNG tiles")

    monkeypatch.setattr("api.routes.gee_tiles.get_cached_tile", fail_get_cached_tile)

    r = client.get("/reservoirs/gobind_sagar/sar-tile-raster/2020-01-05/8/10/20?composite=vh")

    assert r.status_code == 200
    assert r.content == b"cached-png"
    assert r.headers["cache-control"] == "public, max-age=86400, immutable"


def test_sar_tile_raster_uses_local_renderer_before_gee(
    client, seeded_observation_rows, monkeypatch, tmp_path
):
    vh = tmp_path / "vh.tif"
    vh.write_bytes(b"placeholder")
    asset = SarAsset(
        reservoir_id="gobind_sagar",
        acquisition_date="2020-01-05",
        scene_id="S1A_TEST_0001",
        vv_path=None,
        vh_path=vh,
        water_mask_path=None,
        bounds=None,
        min_zoom=8,
        max_zoom=14,
        status="ready",
    )

    def fail_get_cached_tile(*args, **kwargs):
        raise AssertionError("Earth Engine should not be minted when local render succeeds")

    monkeypatch.setattr("api.routes.sar_assets.find_asset", lambda *args, **kwargs: asset)
    monkeypatch.setattr("api.routes.sar_assets.render_tile", lambda *args, **kwargs: b"local-png")
    monkeypatch.setattr("api.routes.gee_tiles.get_cached_tile", fail_get_cached_tile)

    r = client.get("/reservoirs/gobind_sagar/sar-tile-raster/2020-01-05/8/10/20?composite=vh")

    assert r.status_code == 200
    assert r.content == b"local-png"


def test_current_estimate_endpoint_serves_selected_imagery_state(client, seeded_observation_rows):
    r = client.get("/reservoirs/gobind_sagar/current-estimate?date=2020-01-05")
    assert r.status_code == 200
    body = r.json()
    assert body["acquisition_date"] == "2020-01-05"
    assert body["area_km2"] == 120.5
    assert body["live_storage_bcm"] > 0
    assert body["level_m"] > 0
    assert body["pct_filled"] > 0
    assert isinstance(body["is_extrapolated"], bool)


def test_acquisitions_use_latest_historical_value_not_curve_value(
    client, session, seeded_observation_rows
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
                ('thein', '2026-07-15', 57.65, 0.88, 'backfill://historical-check',
                 'otsu_vh', 'v1', ARRAY['S1A_HISTORICAL_CHECK'], 27, 'ASC', 'v1', 0,
                 CAST('{}' AS jsonb))
            """
        )
    )
    row = next(
        x for x in client.get("/reservoirs/thein/acquisitions").json() if x["date"] == "2026-07-15"
    )
    assert row["historical_date"] == "2026-07-16"
    assert row["level_m"] == 501.89
    assert row["live_storage_bcm"] == 0.695
    assert row["pct_filled"] == pytest.approx(29.650170648464165, abs=0.001)


def test_current_estimate_can_compute_from_curve_when_observation_not_backfilled(
    client, session, seeded_observation_rows
):
    session.execute(
        text(
            """
            INSERT INTO rating_curve
              (reservoir_id, version, fit_type, area_to_storage_params, area_to_level_params,
               frl_anchor, observed_range, fit_metrics, valid_from, is_active)
            VALUES
              ('gobind_sagar', 'rc_api_read', 'empirical',
               '{"coeffs": [0.01, 0]}'::jsonb, '{"coeffs": [0.1, 400]}'::jsonb,
               '{"frl_m": 512, "capacity_bcm": 6.229}'::jsonb,
               '{"area_min": 0, "area_max": 300}'::jsonb, '{}'::jsonb,
               CURRENT_DATE, true)
            """
        )
    )
    session.execute(
        text(
            """
            INSERT INTO observation
                (reservoir_id, acquisition_date, surface_area, area_confidence,
                 water_mask_ref, extraction_method, extraction_version, scene_ids,
                 orbit_relative, pass_direction, aoi_version, layover_shadow_fraction,
                 processing_params)
            VALUES
                ('gobind_sagar', '2020-02-05', 150.0, 0.88, 'backfill://curve-read',
                 'otsu_vh', 'v1', ARRAY['S1A_TEST_0004'], 27, 'ASC', 'v1', 0,
                 CAST('{}' AS jsonb))
            """
        )
    )

    r = client.get("/reservoirs/gobind_sagar/current-estimate?date=2020-02-05")
    assert r.status_code == 200
    body = r.json()
    assert body["live_storage_bcm"] == 1.5
    assert body["level_m"] == 415.0
    assert body["pct_filled"] > 0

    acq = client.get("/reservoirs/gobind_sagar/acquisitions").json()
    row = next(x for x in acq if x["date"] == "2020-02-05")
    # This timeline endpoint intentionally shows historical ground truth only;
    # the curve remains available through current-estimate for production inference.
    assert row["live_storage_bcm"] is None
    assert row["level_m"] is None
    assert row["is_extrapolated"] is False


def test_synthetic_rows_never_mint_tiles_or_freshen_staleness(client, seeded_observation_rows):
    # sar-tiles: the synthetic date has no real scene to mint -> 404, not a fake tile
    assert client.get("/reservoirs/gobind_sagar/sar-tiles?date=2026-01-01").status_code == 404
    assert client.get("/reservoirs/gobind_sagar/sar-tiles?date=not-a-date").status_code == 422
    # status: last_acquisition_date must come from real rows only, so the synthetic
    # 2026 row cannot make stale data look fresh
    status = client.get("/reservoirs/gobind_sagar/status").json()
    assert status["last_acquisition_date"] != "2026-01-01"


@pytest.fixture
def seeded_mask_rows(client, session):
    """One real observation WITH a mask geometry plus a NEWER synthetic-provenance row
    that also has a mask (C5) — /geojson/water-extent must serve the real one."""
    for d, area, sid in (
        ("2020-01-05", 120.5, "S1A_TEST_0001"),
        ("2026-01-01", 999.0, "synthetic"),
    ):
        session.execute(
            text(
                """
                INSERT INTO observation
                    (reservoir_id, acquisition_date, surface_area, area_confidence,
                     water_mask_ref, extraction_method, extraction_version, scene_ids,
                     orbit_relative, pass_direction, aoi_version, layover_shadow_fraction,
                     processing_params, water_mask_geom)
                VALUES
                    ('gobind_sagar', :d, :area, 0.9, :ref, 'otsu_vh', 'v1',
                     ARRAY[:sid], 27, 'ASC', 'v1', 0, CAST('{}' AS jsonb),
                     ST_Multi(ST_GeomFromText(
                       'POLYGON((76.4 31.4, 76.5 31.4, 76.5 31.5, 76.4 31.5, 76.4 31.4))', 4326)))
                ON CONFLICT (reservoir_id, acquisition_date) DO UPDATE SET
                    surface_area = EXCLUDED.surface_area,
                    extraction_method = EXCLUDED.extraction_method,
                    scene_ids = EXCLUDED.scene_ids,
                    water_mask_geom = EXCLUDED.water_mask_geom
                """
            ),
            {"d": d, "area": area, "ref": f"backfill://{sid}", "sid": sid},
        )


def test_water_extent_excludes_synthetic_masks(client, seeded_mask_rows):
    # C5: the synthetic 2026 row has a mask AND a newer date — if the provenance
    # filter is missing, DISTINCT ON picks it as the "latest" extent.
    gj = client.get("/geojson/water-extent").json()
    gs = [f for f in gj["features"] if f["properties"]["reservoir_id"] == "gobind_sagar"]
    assert len(gs) == 1
    assert gs[0]["properties"]["acquisition_date"] == "2020-01-05"
    assert gs[0]["geometry"]["type"] in ("Polygon", "MultiPolygon")


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
