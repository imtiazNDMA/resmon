"""Real Google Earth Engine geometry extraction for the map overlays.

Produces georeferenced GeoJSON from **live GEE** (requires a service-account key):
- ``derive_aoi`` — reservoir water footprint from JRC Global Surface Water (FR-RS-1).
- ``delineate_catchment`` — HydroSHEDS HydroBASINS unit at the dam (FR-DE-7).
- ``latest_water_extent`` — current Sentinel-1 VH water mask + true area (FR-RS-2/3).

Returns plain GeoJSON dicts so the caller can persist via PostGIS ``ST_GeomFromGeoJSON``.
This is the production path the synthetic framework stood in for; it runs only when GEE
credentials are present.
"""

from __future__ import annotations

import json
import os

from tenacity import retry, stop_after_attempt, wait_exponential

_INITED = False

# GEE occasionally returns transient HTTP 500s on heavy reductions; retry with backoff.
_gee_retry = retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=20))

JRC_GSW = "JRC/GSW1_4/GlobalSurfaceWater"
S1_GRD = "COPERNICUS/S1_GRD"


def init_ee(key_file: str | None = None) -> None:
    global _INITED
    if _INITED:
        return
    import ee

    key_file = key_file or os.environ.get("GEE_SA_KEY_FILE") or "geeservice.json"
    with open(key_file) as fh:
        info = json.load(fh)
    ee.Initialize(
        ee.ServiceAccountCredentials(info["client_email"], key_file),
        project=info["project_id"],
    )
    _INITED = True


@_gee_retry
def derive_aoi(lon: float, lat: float, occurrence_pct: int = 25, buffer_m: int = 12000) -> dict:
    """Reservoir AOI = JRC-GSW pixels with water-occurrence ≥ threshold near the dam,
    vectorised and simplified. Sized to the historical max water extent (FR-RS-1)."""
    import ee

    init_ee()
    region = ee.Geometry.Point([lon, lat]).buffer(buffer_m).bounds()
    gsw = ee.Image(JRC_GSW).select("occurrence")
    fc = (
        gsw.gte(occurrence_pct)
        .selfMask()
        .reduceToVectors(
            geometry=region, scale=90, maxPixels=int(1e9), bestEffort=True, geometryType="polygon"
        )
    )
    return fc.geometry().simplify(120).getInfo()


@_gee_retry
def delineate_catchment(lon: float, lat: float, level: int = 7) -> dict:
    """HydroSHEDS HydroBASINS unit containing the dam point (FR-DE-7)."""
    import ee

    init_ee()
    dam = ee.Geometry.Point([lon, lat])
    basins = ee.FeatureCollection(f"WWF/HydroSHEDS/v1/Basins/hybas_{level}").filterBounds(dam)
    return basins.geometry().simplify(300).getInfo()


@_gee_retry
def latest_water_extent(aoi_geojson: dict, vh_threshold: float = -18.0) -> dict:
    """Most-recent Sentinel-1 VH water mask clipped to the AOI: returns GeoJSON, true area
    (km², via ``pixelArea``), acquisition date, and scene id (FR-RS-2/3). Vectorised at a
    coarse scale to keep the GEE reduction light."""
    import ee

    init_ee()
    aoi = ee.Geometry(aoi_geojson)
    coll = (
        ee.ImageCollection(S1_GRD)
        .filterBounds(aoi)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
        .sort("system:time_start", False)
    )
    latest = ee.Image(coll.first())
    info = latest.toDictionary(
        ["system:index", "relativeOrbitNumber_start", "orbitProperties_pass"]
    )
    acq_date = ee.Date(latest.get("system:time_start")).format("YYYY-MM-dd").getInfo()
    props = info.getInfo()
    # Smooth a touch to reduce speckle before thresholding, then vectorise coarsely (90 m)
    # so reduceToVectors stays well within GEE limits even on the larger reservoirs.
    water = (
        latest.select("VH")
        .focal_median(50, "circle", "meters")
        .lt(vh_threshold)
        .selfMask()
        .clip(aoi)
    )
    area_m2 = (
        water.multiply(ee.Image.pixelArea())
        .reduceRegion(ee.Reducer.sum(), aoi, 30, maxPixels=int(1e10), bestEffort=True)
        .get("VH")
        .getInfo()
    )
    geom = (
        water.reduceToVectors(
            geometry=aoi, scale=90, maxPixels=int(1e10), bestEffort=True, geometryType="polygon"
        )
        .geometry()
        .simplify(90)
        .getInfo()
    )
    return {
        "geojson": geom,
        "area_km2": (area_m2 or 0.0) / 1e6,
        "acquisition_date": acq_date,
        "scene_id": str(props.get("system:index")),
        "orbit_relative": int(props.get("relativeOrbitNumber_start") or 0),
        "pass_direction": "ASC" if props.get("orbitProperties_pass") == "ASCENDING" else "DESC",
    }
