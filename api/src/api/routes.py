"""Public REST/JSON + GeoJSON endpoints (FR-API-1/2). All read-only; no auth in v1."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import api.repositories as repo
from api.db import get_db

router = APIRouter()


@router.get("/reservoirs", tags=["reservoirs"])
def list_reservoirs(db: Session = Depends(get_db)) -> list[dict]:
    return repo.list_reservoirs(db)


@router.get("/reservoirs/{rid}", tags=["reservoirs"])
def get_reservoir(rid: str, db: Session = Depends(get_db)) -> dict:
    res = repo.get_reservoir(db, rid)
    if res is None:
        raise HTTPException(status_code=404, detail=f"reservoir {rid!r} not found")
    return res


@router.get("/reservoirs/{rid}/status", tags=["reservoirs"])
def reservoir_status(rid: str, db: Session = Depends(get_db)) -> dict:
    status = repo.latest_status(db, rid)
    if status is None:
        raise HTTPException(status_code=404, detail=f"no data for reservoir {rid!r}")
    return status


@router.get("/reservoirs/{rid}/timeseries", tags=["reservoirs"])
def reservoir_timeseries(
    rid: str, limit: int = Query(default=200, ge=1, le=2000), db: Session = Depends(get_db)
) -> list[dict]:
    return repo.timeseries(db, rid, limit)


@router.get("/reservoirs/{rid}/forecast", tags=["forecast"])
def reservoir_forecast(rid: str, db: Session = Depends(get_db)) -> dict:
    points = repo.latest_forecast(db, rid)
    return {"reservoir_id": rid, "horizon": len(points), "points": points}


@router.get("/release-risk", tags=["release-risk"])
def fleet_release_risk(db: Session = Depends(get_db)) -> list[dict]:
    return repo.fleet_release_risk(db)


@router.get("/accuracy", tags=["accuracy"])
def accuracy(db: Session = Depends(get_db)) -> dict:
    return repo.accuracy(db)


def _feature_collection(rows: list[dict], props) -> dict:
    feats = []
    for r in rows:
        if not r.get("g"):
            continue
        feats.append({"type": "Feature", "geometry": json.loads(r["g"]), "properties": props(r)})
    return {"type": "FeatureCollection", "features": feats}


@router.get("/geojson/aoi", tags=["geojson"])
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


@router.get("/geojson/catchment", tags=["geojson"])
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


@router.get("/geojson/water-extent", tags=["geojson"])
def geojson_water_extent(db: Session = Depends(get_db)) -> dict:
    """Latest Sentinel-1 water extent per reservoir (with true area + acquisition date)."""
    return _feature_collection(
        repo.water_extent_features(db),
        lambda r: {
            "reservoir_id": r["reservoir_id"],
            "name": r["name"],
            "surface_area_km2": float(r["surface_area"]),
            "acquisition_date": str(r["acquisition_date"]),
        },
    )


@router.get("/geojson/reservoirs", tags=["geojson"])
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
                    "frl_m": float(r["frl_m"]),
                    "risk_level": r["risk_level"],
                    "release_probability": (
                        float(r["release_probability"])
                        if r["release_probability"] is not None
                        else None
                    ),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}
