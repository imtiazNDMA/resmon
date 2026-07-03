"""Stage-1.2 historical extraction backfill (Replan.md §3): the dense ``area(t)`` series.

Runs the same adaptive per-scene extraction as ``gee_real.latest_water_extent`` over the
*entire* Sentinel-1 archive for a reservoir's frozen orbit/pass, batched so ~280 scenes
per reservoir cost ~30 chunked round-trips instead of ~560 sequential ones:

1. one ``getInfo`` lists every qualifying scene id (orbit/pass + footprint-contains-AOI);
2. per chunk, one ``getInfo`` pulls smoothed-VH histograms for all scenes at once;
3. Otsu / valley-ratio / Fisher gates run client-side (shared ``extractors`` code —
   abstained scenes are *recorded* as abstained, never given a made-up area);
4. per chunk, one ``getInfo`` reduces true pixel areas for the non-abstained scenes,
   each masked at its own client-computed threshold (server-side id→threshold dict).

Results append to ``data/backfill/area_series_<slug>.csv`` after every chunk, so the run
is crash-safe and re-runs skip already-processed scene ids. The AOI is derived once and
cached to disk — a re-run can never silently shift the series geometry.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from remote_sensing.extractors import (
    SEPARABILITY_FLOOR,
    VALLEY_RATIO_MAX,
    fisher_from_histogram,
    otsu_from_histogram,
    valley_ratio,
)
from remote_sensing.gee_real import (
    S1_GRD,
    GeeExtractionError,
    SceneUnavailableError,
    derive_aoi,
    init_ee,
)

log = logging.getLogger(__name__)

_HIST_SCALE_M = 30
_AREA_SCALE_M = 10
_SMOOTH_RADIUS_M = 50.0
_GEE_PASS = {"ASC": "ASCENDING", "DESC": "DESCENDING"}

CSV_COLUMNS = [
    "scene_id",
    "acquisition_date",
    "orbit_relative",
    "pass_direction",
    "status",  # ok | abstain | error
    "area_km2",
    "threshold_db",
    "otsu_eta",
    "valley_ratio",
    "separability",
    "detail",
]


@dataclass(frozen=True)
class SceneResult:
    scene_id: str
    acquisition_date: str
    orbit_relative: int
    pass_direction: str
    status: str
    area_km2: float | None = None
    threshold_db: float | None = None
    otsu_eta: float | None = None
    valley_ratio: float | None = None
    separability: float | None = None
    detail: str = ""


def load_or_derive_aoi(slug: str, lon: float, lat: float, cache_dir: Path) -> dict:
    """Derive the reservoir AOI once and cache it: the whole series must share one
    geometry, so re-runs load the cached polygon instead of re-deriving (GSW updates or
    parameter tweaks would otherwise silently shift every subsequent area)."""
    cache = cache_dir / f"aoi_{slug}.geojson"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    aoi = derive_aoi(lon, lat)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(aoi), encoding="utf-8")
    log.info("derived + cached AOI for %s -> %s", slug, cache)
    return aoi


def _filtered_collection(aoi: Any, orbit_relative: int, pass_direction: str) -> Any:
    import ee

    gee_pass = _GEE_PASS.get(pass_direction.upper(), pass_direction.upper())
    return (
        ee.ImageCollection(S1_GRD)
        .filterBounds(aoi)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
        .filter(ee.Filter.eq("relativeOrbitNumber_start", int(orbit_relative)))
        .filter(ee.Filter.eq("orbitProperties_pass", gee_pass))
        .filter(ee.Filter.contains(leftField=".geo", rightValue=aoi))
    )


def list_scene_ids(aoi_geojson: dict, orbit_relative: int, pass_direction: str) -> list[str]:
    """Every qualifying scene id (frozen orbit/pass, footprint contains AOI), oldest first."""
    import ee

    init_ee()
    aoi = ee.Geometry(aoi_geojson)
    coll = _filtered_collection(aoi, orbit_relative, pass_direction).sort("system:time_start")
    ids = coll.aggregate_array("system:index").getInfo() or []
    if not ids:
        raise SceneUnavailableError(
            f"no S1 IW/VH scenes fully cover the AOI on orbit {orbit_relative} {pass_direction}"
        )
    return [str(i) for i in ids]


def _smoothed_vh(img: Any) -> Any:
    import ee

    return ee.Image(img).select("VH").focal_median(_SMOOTH_RADIUS_M, "circle", "meters")


def _chunk_histograms(aoi: Any, coll: Any, ids: list[str]) -> list[dict]:
    """One getInfo: smoothed-VH histogram + metadata for every scene in the chunk."""
    import ee

    chunk = coll.filter(ee.Filter.inList("system:index", ids))

    def per_scene(img: object) -> object:
        image = ee.Image(img)
        vh = _smoothed_vh(image)
        return ee.Feature(
            None,
            {
                "id": image.get("system:index"),
                "date": ee.Date(image.get("system:time_start")).format("YYYY-MM-dd"),
                "orbit": image.get("relativeOrbitNumber_start"),
                "pass": image.get("orbitProperties_pass"),
                "hist": vh.reduceRegion(
                    reducer=ee.Reducer.histogram(maxBuckets=256),
                    geometry=aoi,
                    scale=_HIST_SCALE_M,
                    crs=image.select("VH").projection(),
                    maxPixels=int(1e10),
                ).get("VH"),
            },
        )

    feats = (chunk.map(per_scene).getInfo() or {}).get("features", [])
    return [f["properties"] for f in feats]


def _chunk_areas(aoi: Any, coll: Any, thresholds: dict[str, float]) -> dict[str, float]:
    """One getInfo: true pixel area for every non-abstained scene in the chunk, each
    masked at its own client-computed Otsu threshold (server-side id→threshold dict).
    Missing/None areas are surfaced per scene, never coerced to 0 km²."""
    import ee

    if not thresholds:
        return {}
    chunk = coll.filter(ee.Filter.inList("system:index", sorted(thresholds)))
    lut = ee.Dictionary({k: float(v) for k, v in thresholds.items()})

    def per_scene(img: object) -> object:
        image = ee.Image(img)
        vh = _smoothed_vh(image)
        thr = ee.Number(lut.get(image.get("system:index")))
        water = vh.lt(thr).selfMask().clip(aoi)
        area = (
            water.multiply(ee.Image.pixelArea())
            .reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=aoi,
                scale=_AREA_SCALE_M,
                crs=image.select("VH").projection(),
                maxPixels=int(1e10),
            )
            .get("VH")
        )
        return ee.Feature(None, {"id": image.get("system:index"), "area_m2": area})

    feats = (chunk.map(per_scene).getInfo() or {}).get("features", [])
    out: dict[str, float] = {}
    for f in feats:
        props = f["properties"]
        if props.get("area_m2") is not None:
            out[str(props["id"])] = float(props["area_m2"])
    return out


def gate_scene(counts: list, centers: list) -> tuple[str, dict[str, float]]:
    """Shared client-side threshold + abstain decision for one scene's histogram.
    Returns (status, stats) where status is ``ok`` or ``abstain``."""
    threshold, eta = otsu_from_histogram(counts, centers)
    vr = valley_ratio(counts, centers, threshold)
    sep = fisher_from_histogram(counts, centers, threshold)
    stats = {"threshold_db": threshold, "otsu_eta": eta, "valley_ratio": vr, "separability": sep}
    if vr > VALLEY_RATIO_MAX or sep < SEPARABILITY_FLOOR:
        return "abstain", stats
    return "ok", stats


def process_chunk(
    aoi_geojson: dict, orbit_relative: int, pass_direction: str, ids: list[str]
) -> list[SceneResult]:
    """Histogram pass -> client-side gates -> area pass, for one chunk of scene ids."""
    import ee

    init_ee()
    aoi = ee.Geometry(aoi_geojson)
    coll = _filtered_collection(aoi, orbit_relative, pass_direction)

    results: list[SceneResult] = []
    thresholds: dict[str, float] = {}

    for props in _chunk_histograms(aoi, coll, ids):
        sid = str(props["id"])
        date = str(props["date"])
        orbit = int(props["orbit"])
        pdir = "ASC" if props["pass"] == "ASCENDING" else "DESC"
        hist = props.get("hist") or {}
        counts, centers = hist.get("histogram"), hist.get("bucketMeans")
        if not counts or not centers:
            results.append(
                SceneResult(sid, date, orbit, pdir, "error", detail="empty VH histogram")
            )
            continue
        status, stats = gate_scene(counts, centers)
        detail = "histogram not bimodal" if status == "abstain" else ""
        if status == "ok":
            thresholds[sid] = stats["threshold_db"]
        results.append(
            SceneResult(
                sid,
                date,
                orbit,
                pdir,
                status,
                threshold_db=stats["threshold_db"],
                otsu_eta=stats["otsu_eta"],
                valley_ratio=stats["valley_ratio"],
                separability=stats["separability"],
                detail=detail,
            )
        )

    areas = _chunk_areas(aoi, coll, thresholds)
    final: list[SceneResult] = []
    for r in results:
        if r.status != "ok":
            final.append(r)
        elif r.scene_id in areas:
            final.append(replace(r, area_km2=areas[r.scene_id] / 1e6))
        else:
            # A null reduction is an error to investigate, never a 0 km² observation.
            final.append(replace(r, status="error", detail="area reduction returned null"))
    return final


__all__ = [
    "CSV_COLUMNS",
    "GeeExtractionError",
    "SceneResult",
    "SceneUnavailableError",
    "gate_scene",
    "list_scene_ids",
    "load_or_derive_aoi",
    "process_chunk",
]
