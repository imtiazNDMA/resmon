"""Public REST/JSON + GeoJSON endpoints (FR-API-1/2). All read-only; no auth in v1.

Every route declares a typed ``response_model`` (D5): the Pydantic models coerce
Postgres ``Decimal`` to JSON numbers and publish a real OpenAPI contract.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import api.gee_tiles as gee_tiles
import api.repositories as repo
from api.db import get_db
from api.schemas import (
    AccuracyReport,
    AcquisitionOut,
    AoiProperties,
    CatchmentProperties,
    FeatureCollection,
    ForecastResponse,
    ReleaseRiskEntry,
    ReservoirDetail,
    ReservoirMarkerProperties,
    ReservoirStatus,
    ReservoirSummary,
    SarTileOut,
    TimeseriesPoint,
    WaterExtentProperties,
)

router = APIRouter()


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


@router.get("/reservoirs/{rid}/sar-tiles", tags=["reservoirs"], response_model=SarTileOut)
def reservoir_sar_tiles(rid: str, date: str, db: Session = Depends(get_db)) -> dict:
    """Live Sentinel-1 tile URL for the acquisition on ``date`` (503 when GEE is down)."""
    _ensure_reservoir(db, rid)
    scene_id = repo.scene_id_for_date(db, rid, date)
    if scene_id is None:
        raise HTTPException(status_code=404, detail=f"no acquisition on {date}")
    try:
        url, expires = gee_tiles.get_cached_tile(rid, date, scene_id)
    except gee_tiles.GeeUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"live imagery unavailable: {exc}") from exc
    return {"tile_url": url, "expires_at": expires.isoformat()}


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
