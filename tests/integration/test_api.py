"""API endpoint tests via TestClient, with get_db overridden to the test session so the
HTTP layer reads the uncommitted pipeline output in this transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from api.db import get_db
from api.main import app
from api.pmd_client import PmdCacheResult, PmdConfigError, pmd_source
from api.routes import get_pmd_monitor_client
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
    for path in ("/geojson/catchment", "/geojson/subbasins", "/geojson/water-extent"):
        layer = client.get(path).json()
        assert layer["type"] == "FeatureCollection"
    districts = client.get("/geojson/districts").json()
    assert districts["type"] == "FeatureCollection"
    assert len(districts["features"]) > 0
    assert districts["features"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_geojson_subbasins_serves_topology_and_headwater_flag(client, conn, add_reservoir):
    rid = add_reservoir("subbasin_res")
    # 2 drains into 1; nothing drains into 2, so only 2 is a headwater.
    conn.execute(
        text(
            """
            INSERT INTO catchment_subbasin
              (reservoir_id, hybas_id, next_down, is_headwater, geom, catchment_version)
            VALUES
              (:rid, 4070000010, 0, false,
               ST_GeomFromText('MULTIPOLYGON(((76 31,76.1 31,76.1 31.1,76 31.1,76 31)))', 4326),
               'hybas7_v1'),
              (:rid, 4070000020, 4070000010, true,
               ST_GeomFromText('MULTIPOLYGON(((76.1 31,76.2 31,76.2 31.1,76.1 31.1,76.1 31)))',
                               4326),
               'hybas7_v1')
            """
        ),
        {"rid": rid},
    )
    gj = client.get("/geojson/subbasins").json()
    feats = [f for f in gj["features"] if f["properties"]["reservoir_id"] == rid]
    assert len(feats) == 2
    assert all(f["geometry"]["type"] in ("Polygon", "MultiPolygon") for f in feats)
    by_id = {f["properties"]["hybas_id"]: f["properties"] for f in feats}
    assert by_id[4070000020]["is_headwater"] is True
    assert by_id[4070000020]["next_down"] == 4070000010
    assert by_id[4070000010]["is_headwater"] is False
    assert by_id[4070000010]["version"] == "hybas7_v1"


def test_geojson_subbasins_stays_empty_when_topology_missing(client, conn, add_reservoir):
    rid = add_reservoir("subbasin_fallback_res")
    conn.execute(
        text(
            """
            UPDATE reservoir
            SET catchment_geom = ST_GeomFromText(
                  'MULTIPOLYGON(((75.9 30.9,76.3 30.9,76.3 31.3,75.9 31.3,75.9 30.9)))',
                  4326
                )
            WHERE reservoir_id = :rid
            """
        ),
        {"rid": rid},
    )

    gj = client.get("/geojson/subbasins").json()
    feats = [f for f in gj["features"] if f["properties"]["reservoir_id"] == rid]

    assert feats == []


def test_geojson_hydrologic_subbasins_can_filter_by_reservoir(client, conn, add_reservoir):
    rid = add_reservoir("hydro_subbasin_res")
    other = add_reservoir("other_hydro_subbasin_res")
    conn.execute(
        text(
            """
            INSERT INTO catchment_subbasin
              (reservoir_id, hybas_id, next_down, is_headwater, geom, catchment_version)
            VALUES
              (:rid, 4070000010, 0, true,
               ST_GeomFromText('MULTIPOLYGON(((76 31,76.1 31,76.1 31.1,76 31.1,76 31)))', 4326),
               'hybas7_v1'),
              (:other, 4070000020, 0, true,
               ST_GeomFromText('MULTIPOLYGON(((77 31,77.1 31,77.1 31.1,77 31.1,77 31)))', 4326),
               'hybas7_v1')
            """
        ),
        {"rid": rid, "other": other},
    )

    gj = client.get(f"/geojson/hydrologic/subbasins?reservoir_id={rid}&resolution=web").json()
    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == 1
    assert gj["features"][0]["properties"]["reservoir_id"] == rid


def test_geojson_hydrologic_flowlines_serves_clipped_network(client, conn, add_reservoir):
    rid = add_reservoir("flowline_res")
    conn.execute(
        text(
            """
            INSERT INTO catchment_flowline
              (reservoir_id, flowline_id, downstream_id, stream_order, upstream_area_km2,
               length_km, is_main_stem, geom, source_dataset, version)
            VALUES
              (:rid, 1001, NULL, 3, 1200.5, 42.25, true,
               ST_Multi(ST_GeomFromText('LINESTRING(76 31,76.1 31.1)', 4326)),
               'hydrorivers', 'hydrorivers_v1'),
              (:rid, 1002, 1001, 1, 120.0, 12.0, false,
               ST_Multi(ST_GeomFromText('LINESTRING(76.2 31,76.1 31.1)', 4326)),
               'hydrorivers', 'hydrorivers_v1')
            """
        ),
        {"rid": rid},
    )

    gj = client.get(f"/geojson/hydrologic/flowlines?reservoir_id={rid}&min_order=2").json()
    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == 1
    feat = gj["features"][0]
    assert feat["geometry"]["type"] in ("LineString", "MultiLineString")
    assert feat["properties"] == {
        "reservoir_id": rid,
        "flowline_id": 1001,
        "downstream_id": None,
        "stream_order": 3,
        "upstream_area_km2": 1200.5,
        "length_km": 42.25,
        "is_main_stem": True,
        "source_dataset": "hydrorivers",
        "version": "hydrorivers_v1",
    }


def test_hydrologic_layer_provenance_endpoint_filters_by_reservoir(client, conn, add_reservoir):
    rid = add_reservoir("provenance_res")
    other = add_reservoir("other_provenance_res")
    conn.execute(
        text(
            """
            INSERT INTO hydrologic_layer_provenance
              (reservoir_id, layer_name, source_dataset, source_version, source_date,
               resolution_m, processed_at, processing_version, simplification_tolerance_deg,
               projection, limitations, metadata_json)
            VALUES
              (:rid, 'subbasins', 'HydroBASINS', 'hybas7_v1', DATE '2026-08-05',
               500, now(), 'prepare_hydrologic_map_layers_v1', 0.0001,
               'EPSG:4326', 'HydroBASINS polygons are cartographic aggregation units.',
               '{"level": 7}'::jsonb),
              (:other, 'subbasins', 'HydroBASINS', 'hybas7_v1', DATE '2026-08-05',
               500, now(), 'prepare_hydrologic_map_layers_v1', 0.0001,
               'EPSG:4326', 'other', '{}'::jsonb)
            """
        ),
        {"rid": rid, "other": other},
    )

    rows = client.get(f"/hydrologic/layers/provenance?reservoir_id={rid}").json()

    assert len(rows) == 1
    assert rows[0]["reservoir_id"] == rid
    assert rows[0]["layer_name"] == "subbasins"
    assert rows[0]["source_dataset"] == "HydroBASINS"
    assert rows[0]["metadata"] == {"level": 7}


def test_geojson_flow_edges_serves_downstream_display_paths(client, conn, add_reservoir):
    rid = add_reservoir("flow_edge_res")
    conn.execute(
        text(
            """
            INSERT INTO catchment_subbasin
              (reservoir_id, hybas_id, next_down, is_headwater, geom, catchment_version)
            VALUES
              (:rid, 4070000010, 0, false,
               ST_GeomFromText('MULTIPOLYGON(((76 31,76.1 31,76.1 31.1,76 31.1,76 31)))', 4326),
               'hybas7_v1'),
              (:rid, 4070000020, 4070000010, true,
               ST_GeomFromText('MULTIPOLYGON(((76.1 31,76.2 31,76.2 31.1,76.1 31.1,76.1 31)))',
                               4326),
               'hybas7_v1')
            """
        ),
        {"rid": rid},
    )

    gj = client.get("/geojson/flow-edges").json()
    feats = [f for f in gj["features"] if f["properties"]["reservoir_id"] == rid]
    assert len(feats) == 2
    assert all(f["geometry"]["type"] == "LineString" for f in feats)
    by_from = {f["properties"]["from_hybas_id"]: f["properties"] for f in feats}
    assert by_from[4070000020]["to_hybas_id"] == 4070000010
    assert by_from[4070000020]["is_headwater"] is True
    assert by_from[4070000020]["distance_to_reservoir_km"] >= 0
    assert by_from[4070000020]["routing_lag_days"] >= 0.25
    assert by_from[4070000010]["to_hybas_id"] is None


def test_geojson_flow_edges_falls_back_to_catchment_centroid_path(client, conn, add_reservoir):
    rid = add_reservoir("flow_edge_fallback_res")
    conn.execute(
        text(
            """
            UPDATE reservoir
            SET catchment_geom = ST_GeomFromText(
                  'MULTIPOLYGON(((75.9 30.9,76.3 30.9,76.3 31.3,75.9 31.3,75.9 30.9)))',
                  4326
                )
            WHERE reservoir_id = :rid
            """
        ),
        {"rid": rid},
    )

    gj = client.get("/geojson/flow-edges").json()
    feats = [f for f in gj["features"] if f["properties"]["reservoir_id"] == rid]

    assert len(feats) == 1
    assert feats[0]["geometry"]["type"] == "LineString"
    assert feats[0]["properties"]["from_hybas_id"] == 0
    assert feats[0]["properties"]["to_hybas_id"] is None
    assert feats[0]["properties"]["is_headwater"] is True
    assert feats[0]["properties"]["routing_lag_days"] >= 0.25


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


class FakePmdClient:
    def __init__(self, *, configured=True, payload=None, cache_status="fetched"):
        self._configured = configured
        self.payload = payload if payload is not None else {
            "type": "FeatureCollection",
            "features": [],
        }
        self.cache_status = cache_status
        self.requests = []

    def configured(self):
        return self._configured

    def cached(self, key, ttl_seconds, fetch, *, fallback_key=None):
        if not self._configured:
            raise PmdConfigError("not configured")
        return PmdCacheResult(fetch(), self.cache_status)

    def get_json(self, path, params=None):
        self.requests.append({"path": path, "params": params})
        return self.payload


def test_weather_pmd_monitor_stations_disabled_without_config(client):
    app.dependency_overrides[get_pmd_monitor_client] = lambda: FakePmdClient(configured=False)
    try:
        response = client.get("/weather/pmd/monitor/stations")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 503


def test_weather_pmd_monitor_stations_serves_typed_geojson(client):
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
                    "rain_24h": 8.2,
                    "warn_rain": "yellow",
                    "status": True,
                },
            }
        ],
    }
    app.dependency_overrides[get_pmd_monitor_client] = lambda: FakePmdClient(payload=payload)
    try:
        response = client.get("/weather/pmd/monitor/stations")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 1
    props = body["features"][0]["properties"]
    assert props["source"] == pmd_source("monitor_stations").source_name
    assert props["temperature_c"] == 31.5
    assert props["rain_24h_mm"] == 8.2
    assert props["cache_status"] == "fetched"
    assert props["stale"] is False


def test_weather_pmd_monitor_stations_accepts_empty_payload(client):
    app.dependency_overrides[get_pmd_monitor_client] = lambda: FakePmdClient(
        payload={"type": "FeatureCollection", "features": []}
    )
    try:
        response = client.get("/weather/pmd/monitor/stations")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 200
    assert response.json() == {"type": "FeatureCollection", "features": []}


def test_weather_pmd_nwfc_observations_disabled_without_config(client):
    app.dependency_overrides[get_pmd_monitor_client] = lambda: FakePmdClient(configured=False)
    try:
        response = client.get("/weather/pmd/nwfc/observations")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 503


def test_weather_pmd_nwfc_observations_serves_typed_geojson(client):
    payload = {
        "data": [
            {
                "lat": "34.0",
                "lon": "72.5",
                "station_id": "nwfc-1",
                "station_code": "NW01",
                "station_name": "Peshawar",
                "valid_time": "2026-08-05T06:00:00+05:00",
                "weather": "Cloudy",
                "weather_icon": "cloudy.png",
                "temperature": 28.1,
                "humidity": 71,
                "rain_24h": 2.4,
            }
        ]
    }
    app.dependency_overrides[get_pmd_monitor_client] = lambda: FakePmdClient(payload=payload)
    try:
        response = client.get("/weather/pmd/nwfc/observations")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 1
    props = body["features"][0]["properties"]
    assert props["source"] == pmd_source("nwfc_observations").source_name
    assert props["station_id"] == "nwfc-1"
    assert props["code"] == "NW01"
    assert props["weather_text"] == "Cloudy"
    assert props["temperature_c"] == 28.1
    assert props["rain_24h_mm"] == 2.4


def test_weather_pmd_nwfc_observations_accepts_empty_payload(client):
    app.dependency_overrides[get_pmd_monitor_client] = lambda: FakePmdClient(payload={"data": []})
    try:
        response = client.get("/weather/pmd/nwfc/observations")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 200
    assert response.json() == {"type": "FeatureCollection", "features": []}


def test_weather_pmd_monitor_glof_observations_disabled_without_config(client):
    app.dependency_overrides[get_pmd_monitor_client] = lambda: FakePmdClient(configured=False)
    try:
        response = client.get("/weather/pmd/monitor/glof-observations")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 503


def test_weather_pmd_monitor_glof_observations_serves_typed_geojson(client):
    payload = [
        {
            "lat": "35.9",
            "lon": "74.3",
            "station_id": "glof-1",
            "station_name": "Hunza GLOF",
            "last_update": "2026-08-05T08:00:00+05:00",
            "connectivity": "online",
            "alert_level": "Watch",
            "rainfall": "9.5",
            "flow": "1.2",
            "water_level": "2.1",
            "temp": "6.3",
        }
    ]
    app.dependency_overrides[get_pmd_monitor_client] = lambda: FakePmdClient(payload=payload)
    try:
        response = client.get("/weather/pmd/monitor/glof-observations")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 1
    props = body["features"][0]["properties"]
    assert props["source"] == pmd_source("monitor_glof_observations").source_name
    assert props["station_id"] == "glof-1"
    assert props["connected"] is True
    assert props["alert_level"] == "Watch"
    assert props["rainfall_mm"] == 9.5
    assert props["flow_cms"] == 1.2
    assert props["water_level_m"] == 2.1


def test_weather_pmd_monitor_glof_observations_accepts_empty_payload(client):
    app.dependency_overrides[get_pmd_monitor_client] = lambda: FakePmdClient(payload=[])
    try:
        response = client.get("/weather/pmd/monitor/glof-observations")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 200
    assert response.json() == {"type": "FeatureCollection", "features": []}


def test_weather_pmd_monitor_lightning_disabled_without_config(client):
    app.dependency_overrides[get_pmd_monitor_client] = lambda: FakePmdClient(configured=False)
    try:
        response = client.get("/weather/pmd/monitor/lightning?hours=6")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 503


def test_weather_pmd_monitor_lightning_serves_typed_geojson(client):
    fake = FakePmdClient(
        payload={
            "data": [
                {
                    "lat": "33.6",
                    "lon": "73.0",
                    "strike_id": "l-1",
                    "timestamp": "2026-08-05T09:00:00+05:00",
                    "polarity": "negative",
                    "peak_current": "18.5",
                    "strokes": "2",
                }
            ]
        }
    )
    app.dependency_overrides[get_pmd_monitor_client] = lambda: fake
    try:
        response = client.get("/weather/pmd/monitor/lightning?hours=12")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 1
    props = body["features"][0]["properties"]
    assert props["source"] == pmd_source("monitor_lightning").source_name
    assert props["strike_id"] == "l-1"
    assert props["window_hours"] == 12
    assert props["peak_current_ka"] == 18.5
    assert props["multiplicity"] == 2.0
    assert fake.requests == [
        {"path": pmd_source("monitor_lightning").upstream_path, "params": {"hours": 12}}
    ]


def test_weather_pmd_monitor_lightning_validates_hours(client):
    response = client.get("/weather/pmd/monitor/lightning?hours=49")

    assert response.status_code == 422


def test_weather_pmd_monitor_lightning_accepts_empty_payload(client):
    app.dependency_overrides[get_pmd_monitor_client] = lambda: FakePmdClient(payload={"data": []})
    try:
        response = client.get("/weather/pmd/monitor/lightning?hours=1")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 200
    assert response.json() == {"type": "FeatureCollection", "features": []}


def test_weather_ffd_waterlevels_disabled_without_config(client):
    app.dependency_overrides[get_pmd_monitor_client] = lambda: FakePmdClient(configured=False)
    try:
        response = client.get("/weather/ffd/waterlevels")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 503


def test_weather_ffd_waterlevels_serves_typed_geojson(client):
    fake = FakePmdClient(
        payload={
            "rows": [
                {
                    "lat": "31.4",
                    "lon": "73.1",
                    "site_id": "ffd-1",
                    "site_name": "River Chenab Gauge",
                    "river_name": "Chenab",
                    "last_update": "2026-08-05T10:00:00+05:00",
                    "water_level": "3.4",
                    "discharge": "12500",
                    "status": "Low Flood",
                    "gauges": '[{"name":"main","level":3.4}]',
                }
            ]
        }
    )
    app.dependency_overrides[get_pmd_monitor_client] = lambda: fake
    try:
        response = client.get("/weather/ffd/waterlevels")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 1
    props = body["features"][0]["properties"]
    assert props["source"] == pmd_source("ffd_waterlevels").source_name
    assert props["station_id"] == "ffd-1"
    assert props["river"] == "Chenab"
    assert props["water_level_m"] == 3.4
    assert props["discharge_cusecs"] == 12500.0
    assert props["gauges"] == [{"name": "main", "level": 3.4}]
    assert fake.requests == [{"path": pmd_source("ffd_waterlevels").upstream_path, "params": None}]


def test_weather_ffd_waterlevels_accepts_empty_payload(client):
    app.dependency_overrides[get_pmd_monitor_client] = lambda: FakePmdClient(payload={"rows": []})
    try:
        response = client.get("/weather/ffd/waterlevels")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 200
    assert response.json() == {"type": "FeatureCollection", "features": []}


def test_weather_pmd_monitor_warnings_serves_typed_geojson(client):
    fake = FakePmdClient(
        payload=[
            {
                "geometry": '{"type":"Polygon","coordinates":[[[73,33],[74,33],[74,34],[73,33]]]}',
                "warning_id": "w-1",
                "severity": "Warning",
                "element": "Heavy Rain",
                "forecast_time": "2026-08-05T12:00:00+05:00",
                "issued_at": "2026-08-05T06:00:00+05:00",
                "message": "Heavy rainfall expected",
                "district": "Rawalpindi",
            }
        ]
    )
    app.dependency_overrides[get_pmd_monitor_client] = lambda: fake
    try:
        response = client.get("/weather/pmd/monitor/warnings")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 200
    body = response.json()
    assert body["features"][0]["geometry"]["type"] == "Polygon"
    props = body["features"][0]["properties"]
    assert props["source"] == pmd_source("monitor_warnings").source_name
    assert props["warning_id"] == "w-1"
    assert props["hazard"] == "Heavy Rain"


def test_weather_pmd_monitor_warnings_accepts_empty_payload(client):
    app.dependency_overrides[get_pmd_monitor_client] = lambda: FakePmdClient(payload=[])
    try:
        response = client.get("/weather/pmd/monitor/warnings")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 200
    assert response.json() == {"type": "FeatureCollection", "features": []}


def test_weather_pmd_monitor_monsoon_serves_typed_geojson(client):
    fake = FakePmdClient(
        payload=[
            {
                "lat": "30.2",
                "lon": "71.5",
                "id": "m-1",
                "level": "Watch",
                "data_type": "Monsoon Rain",
                "date_time": "2026-08-05T06:00:00+05:00",
                "fc": '[{"period":"24h","rain_mm":18}]',
            }
        ]
    )
    app.dependency_overrides[get_pmd_monitor_client] = lambda: fake
    try:
        response = client.get("/weather/pmd/monitor/monsoon")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 200
    props = response.json()["features"][0]["properties"]
    assert props["source"] == pmd_source("monitor_monsoon").source_name
    assert props["warning_id"] == "m-1"
    assert props["forecast"] == [{"period": "24h", "rain_mm": 18}]


def test_weather_pmd_monitor_monsoon_accepts_empty_payload(client):
    app.dependency_overrides[get_pmd_monitor_client] = lambda: FakePmdClient(payload=[])
    try:
        response = client.get("/weather/pmd/monitor/monsoon")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 200
    assert response.json() == {"type": "FeatureCollection", "features": []}


def test_weather_pmd_monitor_city_forecast_serves_typed_geojson(client):
    fake = FakePmdClient(
        payload=[
            {
                "lat": "33.7",
                "lon": "73.1",
                "city_id": "isb",
                "city_name": "Islamabad",
                "date_time": "2026-08-05T06:00:00+05:00",
                "weather_text": "Cloudy",
                "temp": "31",
                "fc": '[{"t":"+3h","temp":32}]',
            }
        ]
    )
    app.dependency_overrides[get_pmd_monitor_client] = lambda: fake
    try:
        response = client.get("/weather/pmd/monitor/city-forecast")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 200
    props = response.json()["features"][0]["properties"]
    assert props["source"] == pmd_source("monitor_city_forecast").source_name
    assert props["city_id"] == "isb"
    assert props["forecast"] == [{"t": "+3h", "temp": 32}]


def test_weather_pmd_monitor_city_forecast_accepts_empty_payload(client):
    app.dependency_overrides[get_pmd_monitor_client] = lambda: FakePmdClient(payload=[])
    try:
        response = client.get("/weather/pmd/monitor/city-forecast")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 200
    assert response.json() == {"type": "FeatureCollection", "features": []}


class FakePredictionClient(FakePmdClient):
    def get_json(self, path, params=None):
        self.requests.append({"path": path, "params": params})
        if path == "api/modelTimeList":
            return {"data": [{"model_time": "2026-08-05 00:00"}]}
        if path == "api/model":
            return {"frames": [{"forecast_time": "+1h"}, {"forecast_time": "+2h"}]}
        return self.payload


def test_weather_pmd_predictions_serves_metadata_scaffold(client):
    fake = FakePredictionClient()
    app.dependency_overrides[get_pmd_monitor_client] = lambda: fake
    try:
        response = client.get("/weather/pmd/predictions/pmd_pred_hourtpe")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 200
    body = response.json()
    assert body["element"]["data_type"] == "WRFPRS"
    assert body["element"]["element"] == "HOURTPE"
    assert body["run"] == "2026-08-05 00:00"
    assert body["available"] is True
    assert body["metadata_status"] == "metadata-confirmed"
    assert body["steps"] == [
        {
            "date": "+1h",
            "bounds": None,
            "coordinates": None,
            "url": None,
            "cache_status": "fetched",
        },
        {
            "date": "+2h",
            "bounds": None,
            "coordinates": None,
            "url": None,
            "cache_status": "fetched",
        },
    ]
    assert fake.requests == [
        {"path": "api/modelTimeList", "params": {"data_type": "WRFPRS", "element": "HOURTPE"}},
        {
            "path": "api/model",
            "params": {
                "data_type": "WRFPRS",
                "element": "HOURTPE",
                "date_time": "2026-08-05 00:00",
            },
        },
    ]


def test_weather_pmd_predictions_rejects_unknown_element(client):
    response = client.get("/weather/pmd/predictions/nope")

    assert response.status_code == 404


def test_weather_pmd_predictions_disabled_without_config(client):
    app.dependency_overrides[get_pmd_monitor_client] = lambda: FakePmdClient(configured=False)
    try:
        response = client.get("/weather/pmd/predictions/pmd_pred_hourtpe")
    finally:
        app.dependency_overrides.pop(get_pmd_monitor_client, None)

    assert response.status_code == 503


def test_openapi_published(client):
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "Reservoir Monitoring & Analytics API"
    assert "/reservoirs" in schema["paths"]
    # D5: routes declare typed response models — the contract is no longer `{}`.
    ok = schema["paths"]["/reservoirs"]["get"]["responses"]["200"]
    assert ok["content"]["application/json"]["schema"]["items"]["$ref"].endswith("ReservoirSummary")
