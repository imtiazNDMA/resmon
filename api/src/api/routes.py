"""Public REST/JSON + GeoJSON endpoints (FR-API-1/2). All read-only; no auth in v1.

Every route declares a typed ``response_model`` (D5): the Pydantic models coerce
Postgres ``Decimal`` to JSON numbers and publish a real OpenAPI contract.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from datetime import date as Date

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy.orm import Session

import api.gee_tiles as gee_tiles
import api.pmd_client as pmd
import api.repositories as repo
import api.sar_assets as sar_assets
from api.db import get_db
from api.schemas import (
    AccuracyReport,
    AcquisitionOut,
    AoiProperties,
    CatchmentProperties,
    CurrentEstimateOut,
    DistrictBoundaryProperties,
    FeatureCollection,
    FlowEdgeProperties,
    FlowlineProperties,
    ForecastResponse,
    HydrologicLayerProvenanceOut,
    MetForcingOut,
    PmdStationObservationProperties,
    RainfallPointOut,
    ReleaseRiskEntry,
    ReservoirDetail,
    ReservoirMarkerProperties,
    ReservoirStatus,
    ReservoirSummary,
    SarAssetManifestEntryOut,
    SarTileMetricsOut,
    SarTileOut,
    SubBasinProperties,
    TimeseriesPoint,
    WaterExtentProperties,
)

router = APIRouter()

_PMD_CLIENT = pmd.PmdMonitorClient()


def get_pmd_monitor_client() -> pmd.PmdMonitorClient:
    return _PMD_CLIENT


def _ensure_reservoir(db: Session, rid: str) -> None:
    """404 on unknown reservoir id (shared by the additive dashboard endpoints)."""
    if repo.get_reservoir(db, rid) is None:
        raise HTTPException(status_code=404, detail=f"reservoir {rid!r} not found")


@router.get("/reservoirs", tags=["reservoirs"], response_model=list[ReservoirSummary])
def list_reservoirs(db: Session = Depends(get_db)) -> list[dict]:
    return repo.list_reservoirs(db)


@router.get("/reservoirs/{rid}", tags=["reservoirs"], response_model=ReservoirDetail)
def get_reservoir(rid: str, db: Session = Depends(get_db)) -> dict:
    res = repo.get_reservoir(db, rid)
    if res is None:
        raise HTTPException(status_code=404, detail=f"reservoir {rid!r} not found")
    return res


@router.get("/reservoirs/{rid}/status", tags=["reservoirs"], response_model=ReservoirStatus)
def reservoir_status(rid: str, db: Session = Depends(get_db)) -> dict:
    status = repo.latest_status(db, rid)
    if status is None:
        raise HTTPException(status_code=404, detail=f"no data for reservoir {rid!r}")
    return status


@router.get(
    "/reservoirs/{rid}/timeseries", tags=["reservoirs"], response_model=list[TimeseriesPoint]
)
def reservoir_timeseries(
    rid: str, limit: int = Query(default=200, ge=1, le=2000), db: Session = Depends(get_db)
) -> list[dict]:
    return repo.timeseries(db, rid, limit)


@router.get(
    "/reservoirs/{rid}/acquisitions", tags=["reservoirs"], response_model=list[AcquisitionOut]
)
def reservoir_acquisitions(rid: str, db: Session = Depends(get_db)) -> list[dict]:
    """Real (non-stub) SAR acquisition series for the dashboard timeline."""
    _ensure_reservoir(db, rid)
    return repo.acquisitions(db, rid)


@router.get(
    "/reservoirs/{rid}/current-estimate",
    tags=["reservoirs"],
    response_model=CurrentEstimateOut,
)
def reservoir_current_estimate(
    rid: str, date: Date | None = Query(default=None), db: Session = Depends(get_db)
) -> dict:
    """Current reservoir state estimated from the selected SAR acquisition."""
    _ensure_reservoir(db, rid)
    est = repo.current_estimate(db, rid, date.isoformat() if date else None)
    if est is None:
        detail = f"no imagery-derived estimate for reservoir {rid!r}"
        if date:
            detail = f"no imagery-derived estimate for reservoir {rid!r} on {date.isoformat()}"
        raise HTTPException(status_code=404, detail=detail)
    return est


@router.get("/reservoirs/{rid}/sar-tiles", tags=["reservoirs"], response_model=SarTileOut)
def reservoir_sar_tiles(
    rid: str,
    date: Date,
    composite: str = Query(default=gee_tiles.DEFAULT_COMPOSITE),
    db: Session = Depends(get_db),
) -> dict:
    """Tile URL for an acquisition; prefer local SAR assets when cataloged."""
    _ensure_reservoir(db, rid)
    date_key = date.isoformat()
    scene_id = repo.scene_id_for_date(db, rid, date_key)
    if scene_id is None:
        raise HTTPException(status_code=404, detail=f"no acquisition on {date_key}")
    try:
        composite = gee_tiles.validate_composite(composite)
        source = "earth_engine"
        local_asset = sar_assets.find_asset(rid, date_key, composite)
        if local_asset is None:
            _, expires = gee_tiles.get_cached_tile(rid, date_key, scene_id, composite)
        else:
            source = "local"
            expires = datetime.now(UTC) + timedelta(days=365)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except gee_tiles.GeeUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"live imagery unavailable: {exc}") from exc
    url = (
        f"/api/reservoirs/{rid}/sar-tile-raster/{date_key}/{{z}}/{{x}}/{{y}}?composite={composite}"
    )
    return {
        "tile_url": url,
        "expires_at": expires.isoformat(),
        "composite": composite,
        "source": source,
    }


@router.get(
    "/reservoirs/{rid}/sar-assets",
    tags=["reservoirs"],
    response_model=list[SarAssetManifestEntryOut],
)
def reservoir_sar_assets(rid: str, db: Session = Depends(get_db)) -> list[dict]:
    """Local SAR asset coverage available for offline/fast tile rendering."""
    _ensure_reservoir(db, rid)
    return [
        {
            "reservoir_id": entry.reservoir_id,
            "acquisition_date": entry.acquisition_date,
            "scene_id": entry.scene_id,
            "composites": list(entry.composites),
            "bounds": list(entry.bounds) if entry.bounds else None,
            "min_zoom": entry.min_zoom,
            "max_zoom": entry.max_zoom,
        }
        for entry in sar_assets.list_manifest(rid)
    ]


@router.get("/reservoirs/{rid}/sar-tile-raster/{date}/{z}/{x}/{y}", tags=["reservoirs"])
def reservoir_sar_tile_raster(
    rid: str,
    date: Date,
    z: int = Path(ge=0, le=18),
    x: int = Path(ge=0),
    y: int = Path(ge=0),
    composite: str = Query(default=gee_tiles.DEFAULT_COMPOSITE),
    db: Session = Depends(get_db),
) -> Response:
    """Cached XYZ tile proxy so the browser does not call Earth Engine directly."""
    _ensure_reservoir(db, rid)
    date_key = date.isoformat()
    scene_id = repo.scene_id_for_date(db, rid, date_key)
    if scene_id is None:
        raise HTTPException(status_code=404, detail=f"no acquisition on {date_key}")
    try:
        composite = gee_tiles.validate_composite(composite)
        cached = gee_tiles.get_cached_raster_content(rid, date_key, composite, z, x, y)
        if cached is not None:
            gee_tiles.record_rendered_cache_hit()
            return Response(
                content=cached,
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400, immutable"},
            )
        local_asset = sar_assets.find_asset(rid, date_key, composite)
        if local_asset is not None:
            gee_tiles.record_local_asset_hit()
            try:
                started = time.perf_counter()
                content = sar_assets.render_tile(local_asset, composite, z, x, y)
                gee_tiles.put_cached_raster_content(rid, date_key, composite, z, x, y, content)
                gee_tiles.record_local_render((time.perf_counter() - started) * 1000)
                return Response(
                    content=content,
                    media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400, immutable"},
                )
            except sar_assets.LocalSarUnavailable:
                pass
        tile_url, _ = gee_tiles.get_cached_tile(rid, date_key, scene_id, composite)
        started = time.perf_counter()
        content = gee_tiles.get_cached_raster(tile_url, rid, date_key, composite, z, x, y)
        gee_tiles.record_earth_engine_fallback((time.perf_counter() - started) * 1000)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except gee_tiles.GeeUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"live imagery unavailable: {exc}") from exc
    return Response(
        content=content,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


@router.get("/metrics/sar-tiles", tags=["metrics"], response_model=SarTileMetricsOut)
def sar_tile_metrics() -> dict:
    """In-process counters for local SAR tile serving paths."""
    return gee_tiles.sar_tile_metrics().__dict__


@router.get(
    "/reservoirs/{rid}/rainfall", tags=["reservoirs"], response_model=list[RainfallPointOut]
)
def reservoir_rainfall(
    rid: str, window: int = Query(default=90, ge=1, le=730), db: Session = Depends(get_db)
) -> list[dict]:
    """Catchment rainfall over the trailing ``window`` days (empty until live forcing)."""
    _ensure_reservoir(db, rid)
    return repo.rainfall(db, rid, window)


@router.get("/reservoirs/{rid}/met-forcings", tags=["reservoirs"], response_model=MetForcingOut)
def reservoir_met_forcings(rid: str, db: Session = Depends(get_db)) -> dict:
    """Latest catchment-aggregated MET forcings for map overlay toggles."""
    _ensure_reservoir(db, rid)
    return repo.met_forcings(db, rid)


@router.get(
    "/weather/pmd/monitor/stations",
    tags=["weather"],
    response_model=FeatureCollection[PmdStationObservationProperties],
)
def weather_pmd_monitor_stations(
    client: pmd.PmdMonitorClient = Depends(get_pmd_monitor_client),
) -> dict:
    """Live PMD Monitor SYNOP/METAR/AWS station observations as GeoJSON."""
    source = pmd.pmd_source("monitor_stations")
    if not client.configured():
        raise HTTPException(status_code=503, detail="PMD Monitor credentials are not configured")
    try:
        cached = client.cached(
            "pmd_monitor_stations",
            source.ttl_seconds,
            lambda: client.get_json(source.upstream_path),
            fallback_key="pmd_monitor_stations_stale",
        )
    except pmd.PmdUpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return pmd.normalize_monitor_station_features(
        cached.value,
        cache_status=cached.cache_status,
    )


@router.get("/reservoirs/{rid}/forecast", tags=["forecast"], response_model=ForecastResponse)
def reservoir_forecast(rid: str, db: Session = Depends(get_db)) -> dict:
    points = repo.latest_forecast(db, rid)
    return {"reservoir_id": rid, "horizon": len(points), "points": points}


@router.get("/release-risk", tags=["release-risk"], response_model=list[ReleaseRiskEntry])
def fleet_release_risk(db: Session = Depends(get_db)) -> list[dict]:
    return repo.fleet_release_risk(db)


@router.get("/accuracy", tags=["accuracy"], response_model=AccuracyReport)
def accuracy(db: Session = Depends(get_db)) -> dict:
    return repo.accuracy(db)


def _feature_collection(rows: list[dict], props: Callable[[dict], dict]) -> dict:
    feats = []
    for r in rows:
        if not r.get("g"):
            continue
        feats.append({"type": "Feature", "geometry": json.loads(r["g"]), "properties": props(r)})
    return {"type": "FeatureCollection", "features": feats}


@router.get("/geojson/aoi", tags=["geojson"], response_model=FeatureCollection[AoiProperties])
def geojson_aoi(db: Session = Depends(get_db)) -> dict:
    """Reservoir AOI polygons (JRC Global Surface Water footprint)."""
    return _feature_collection(
        repo.aoi_features(db),
        lambda r: {
            "reservoir_id": r["reservoir_id"],
            "name": r["name"],
            "aoi_version": r["aoi_version"],
        },
    )


@router.get(
    "/geojson/catchment", tags=["geojson"], response_model=FeatureCollection[CatchmentProperties]
)
def geojson_catchment(db: Session = Depends(get_db)) -> dict:
    """Upstream catchment polygons (HydroSHEDS HydroBASINS)."""
    return _feature_collection(
        repo.catchment_features(db),
        lambda r: {
            "reservoir_id": r["reservoir_id"],
            "name": r["name"],
            "version": r["catchment_version"],
        },
    )


@router.get(
    "/geojson/subbasins", tags=["geojson"], response_model=FeatureCollection[SubBasinProperties]
)
def geojson_subbasins(db: Session = Depends(get_db)) -> dict:
    """Individual upstream sub-basins, the un-dissolved form of `/geojson/catchment`.
    `is_headwater` marks the top of the catchment."""
    return _feature_collection(
        repo.subbasin_features(db),
        lambda r: {
            "reservoir_id": r["reservoir_id"],
            "hybas_id": r["hybas_id"],
            "next_down": r["next_down"],
            "is_headwater": r["is_headwater"],
            "version": r["catchment_version"],
        },
    )


@router.get(
    "/geojson/hydrologic/subbasins",
    tags=["geojson"],
    response_model=FeatureCollection[SubBasinProperties],
)
def geojson_hydrologic_subbasins(
    reservoir_id: str | None = Query(default=None),
    resolution: str = Query(default="web", pattern="^(web|export)$"),
    db: Session = Depends(get_db),
) -> dict:
    """Reservoir-scoped hydrologic sub-basins.

    ``resolution`` is accepted as the public contract; the repository currently serves
    the web-bounded geometry until export-quality storage is added.
    """
    _ = resolution
    return _feature_collection(
        repo.subbasin_features(db, reservoir_id=reservoir_id),
        lambda r: {
            "reservoir_id": r["reservoir_id"],
            "hybas_id": r["hybas_id"],
            "next_down": r["next_down"],
            "is_headwater": r["is_headwater"],
            "version": r["catchment_version"],
        },
    )


@router.get(
    "/geojson/hydrologic/flowlines",
    tags=["geojson"],
    response_model=FeatureCollection[FlowlineProperties],
)
def geojson_hydrologic_flowlines(
    reservoir_id: str | None = Query(default=None),
    min_order: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> dict:
    """Clipped drainage network vectors for hydrologic map rendering."""
    return _feature_collection(
        repo.flowline_features(db, reservoir_id=reservoir_id, min_order=min_order),
        lambda r: {
            "reservoir_id": r["reservoir_id"],
            "flowline_id": r["flowline_id"],
            "downstream_id": r["downstream_id"],
            "stream_order": r["stream_order"],
            "upstream_area_km2": r["upstream_area_km2"],
            "length_km": r["length_km"],
            "is_main_stem": r["is_main_stem"],
            "source_dataset": r["source_dataset"],
            "version": r["version"],
        },
    )


@router.get(
    "/hydrologic/layers/provenance",
    tags=["geojson"],
    response_model=list[HydrologicLayerProvenanceOut],
)
def hydrologic_layer_provenance(
    reservoir_id: str | None = Query(default=None), db: Session = Depends(get_db)
) -> list[dict]:
    """Source/version/limitation metadata for static hydrologic map layers."""
    return repo.hydrologic_layer_provenance(db, reservoir_id=reservoir_id)


@router.get(
    "/geojson/flow-edges", tags=["geojson"], response_model=FeatureCollection[FlowEdgeProperties]
)
def geojson_flow_edges(db: Session = Depends(get_db)) -> dict:
    """Topology-derived downstream flow edges for animating catchment transport.

    These are display edges from each sub-basin interior point to its downstream
    HydroBASINS neighbour, falling back to the dam point at the outlet. They are a
    visualization scaffold, not calibrated river hydraulics.
    """
    return _feature_collection(
        repo.flow_edge_features(db),
        lambda r: {
            "reservoir_id": r["reservoir_id"],
            "from_hybas_id": r["from_hybas_id"],
            "to_hybas_id": r["to_hybas_id"],
            "is_headwater": r["is_headwater"],
            "distance_to_reservoir_km": r["distance_to_reservoir_km"],
            "routing_lag_days": r["routing_lag_days"],
            "version": r["catchment_version"],
        },
    )


@router.get(
    "/geojson/water-extent",
    tags=["geojson"],
    response_model=FeatureCollection[WaterExtentProperties],
)
def geojson_water_extent(db: Session = Depends(get_db)) -> dict:
    """Latest Sentinel-1 water extent per reservoir (with true area + acquisition date)."""
    return _feature_collection(
        repo.water_extent_features(db),
        lambda r: {
            "reservoir_id": r["reservoir_id"],
            "name": r["name"],
            "surface_area_km2": r["surface_area"],
            "acquisition_date": r["acquisition_date"],
        },
    )


@router.get(
    "/geojson/districts",
    tags=["geojson"],
    response_model=FeatureCollection[DistrictBoundaryProperties],
)
def geojson_districts(db: Session = Depends(get_db)) -> dict:
    """Administrative district boundaries for the map overlay."""
    return _feature_collection(
        repo.district_boundary_features(db),
        lambda r: {
            "district_id": r["district_id"],
            "bbox": [float(x) for x in r["bbox"]],
        },
    )


@router.get(
    "/geojson/reservoirs",
    tags=["geojson"],
    response_model=FeatureCollection[ReservoirMarkerProperties],
)
def reservoir_geojson(db: Session = Depends(get_db)) -> dict:
    """Leaflet-ready FeatureCollection of reservoir markers, coloured by risk_level."""
    features = []
    for r in repo.reservoir_features(db):
        geom = json.loads(r["dam_point_geojson"]) if r["dam_point_geojson"] else None
        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "reservoir_id": r["reservoir_id"],
                    "name": r["name"],
                    "frl_m": r["frl_m"],
                    "risk_level": r["risk_level"],
                    "release_probability": r["release_probability"],
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}
