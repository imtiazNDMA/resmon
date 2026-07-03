"""Real Google Earth Engine geometry extraction for the map overlays.

Produces georeferenced GeoJSON from **live GEE** (requires a service-account key):
- ``derive_aoi`` — reservoir footprint from JRC GSW ``max_extent``, dam-connected (FR-RS-1).
- ``delineate_catchment`` — full HydroBASINS upstream union at the dam (FR-DE-7).
- ``latest_water_extent`` — current Sentinel-1 VH water mask + true area (FR-RS-2/3),
  thresholded **per scene** via the shared Otsu-on-histogram implementation from
  ``extractors`` (ADR-0007: adaptive, never a fixed global threshold), with the same
  bimodality/abstain gate as the array path.

Returns plain GeoJSON dicts so the caller can persist via PostGIS ``ST_GeomFromGeoJSON``.
This is the production path the synthetic framework stood in for; it runs only when GEE
credentials are present. Everything that can be pure Python (Otsu, valley gate, basin
graph traversal) lives client-side so it is unit-testable without credentials.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable, Mapping

from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from remote_sensing.aoi import GSW_MAX_EXTENT_BAND
from remote_sensing.extractors import (
    SEPARABILITY_FLOOR,
    VALLEY_RATIO_MAX,
    OtsuVH,
    fisher_from_histogram,
    otsu_from_histogram,
    valley_ratio,
)

log = logging.getLogger(__name__)

_INITED = False


class GeeExtractionError(RuntimeError):
    """A GEE request succeeded structurally but produced no usable result (empty
    collection, null reduction, ...). Never coerced to a fake value like 0 km²."""


class SceneUnavailableError(GeeExtractionError):
    """No Sentinel-1 scene matches the orbit/pass constraints and fully covers the AOI."""


# GEE occasionally returns transient HTTP 500s on heavy reductions; retry with backoff.
# Semantic failures (GeeExtractionError) are not transient and must not be retried.
_gee_retry = retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_not_exception_type(GeeExtractionError),
    reraise=True,
)

JRC_GSW = "JRC/GSW1_4/GlobalSurfaceWater"
S1_GRD = "COPERNICUS/S1_GRD"

_HIST_SCALE_M = 30  # sampling scale for the threshold histogram (statistics only)
_AREA_SCALE_M = 10  # native S1 GRD pixel — the area reduction is pinned here (B8)
_MAX_UPSTREAM_BASINS = 20_000  # hard bound on the client-side basin graph walk


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
def derive_aoi(lon: float, lat: float, buffer_m: int = 30000) -> dict:
    """Reservoir AOI = JRC-GSW ``max_extent`` water connected to the dam, vectorised and
    simplified. ``max_extent`` (ever-observed water) keeps the rarely-inundated near-FRL
    flood margin inside the AOI, unlike occurrence ≥ 25/50 % cuts. The generous point
    buffer only bounds the vectorisation region — the AOI itself is the dam-connected
    max-extent component, mirroring ``aoi.aoi_bbox_from_occurrence`` (FR-RS-1)."""
    import ee

    init_ee()
    dam = ee.Geometry.Point([lon, lat])
    region = dam.buffer(buffer_m).bounds()
    gsw = ee.Image(JRC_GSW).select(GSW_MAX_EXTENT_BAND)
    polys = (
        gsw.eq(1)
        .selfMask()
        .reduceToVectors(
            geometry=region, scale=60, maxPixels=int(1e9), bestEffort=True, geometryType="polygon"
        )
    )
    # Dam-connected component: keep only polygons touching a small dam neighbourhood
    # (the dam point sits on the dam wall, hence the snap buffer).
    # simplify(300).buffer(250): reduceToVectors emits degenerate/self-intersecting rings
    # that make every later reduceRegion over the AOI fail with GEE internal 500s
    # (found in the 2026-07-03 backfill smoke test). simplify(300) repairs the rings;
    # the outward buffer guarantees no true shoreline pixel is excluded — extra land in
    # the AOI is harmless (Otsu separates it; the area reduction counts water only).
    geom = polys.filterBounds(dam.buffer(1000)).geometry().simplify(300).buffer(250).getInfo()
    if not geom or not geom.get("coordinates"):
        raise GeeExtractionError(
            f"no GSW max-extent water connected to the dam point ({lon}, {lat}); "
            "check dam coordinates or enlarge buffer_m"
        )
    return geom


def _upstream_basin_ids(
    basins: Iterable[Mapping], seed_id: int, *, max_basins: int = _MAX_UPSTREAM_BASINS
) -> set[int]:
    """Pure client-side upstream traversal of a HydroBASINS table.

    ``basins`` are rows with ``HYBAS_ID``/``NEXT_DOWN``; returns the seed basin plus
    every basin whose NEXT_DOWN chain drains into it. Bounded and cycle-safe so a bad
    table cannot hang or explode the walk.
    """
    children: dict[int, list[int]] = {}
    for row in basins:
        children.setdefault(int(row["NEXT_DOWN"]), []).append(int(row["HYBAS_ID"]))
    upstream = {int(seed_id)}
    queue = [int(seed_id)]
    while queue:
        node = queue.pop()
        for child in children.get(node, ()):
            if child not in upstream:
                upstream.add(child)
                queue.append(child)
                if len(upstream) > max_basins:
                    raise GeeExtractionError(
                        f"upstream basin walk exceeded {max_basins} basins from seed {seed_id}; "
                        "HydroBASINS table looks inconsistent"
                    )
    return upstream


@_gee_retry
def delineate_catchment(
    lon: float, lat: float, level: int = 7, expected_km2: float | None = None
) -> dict:
    """Full upstream catchment at the dam (FR-DE-7): find the HydroBASINS level-``level``
    basin containing the dam, walk the ``HYBAS_ID``/``NEXT_DOWN`` graph client-side to
    collect every upstream basin, and union the geometries. The single seed basin alone
    is only a small fraction of the true drainage area (Bhakra ≈ 56,900 km²)."""
    import ee

    init_ee()
    asset = f"WWF/HydroSHEDS/v1/Basins/hybas_{level}"
    coll = ee.FeatureCollection(asset)
    dam = ee.Geometry.Point([lon, lat])
    seed_props = (
        ee.Feature(coll.filterBounds(dam).first()).toDictionary(["HYBAS_ID", "MAIN_BAS"]).getInfo()
    )
    if not seed_props or "HYBAS_ID" not in seed_props:
        raise GeeExtractionError(f"no HydroBASINS level-{level} basin at ({lon}, {lat})")
    seed_id = int(seed_props["HYBAS_ID"])
    main_bas = int(seed_props["MAIN_BAS"])

    # Candidate set = all basins of the same main basin; pull only the topology columns
    # (geometry dropped) so one getInfo stays small, then walk the graph client-side.
    candidates = coll.filter(ee.Filter.eq("MAIN_BAS", main_bas))
    table = candidates.map(
        lambda f: ee.Feature(None).copyProperties(f, ["HYBAS_ID", "NEXT_DOWN"])
    ).getInfo()
    rows = [feat["properties"] for feat in (table or {}).get("features", [])]
    if not rows:
        raise GeeExtractionError(f"empty HydroBASINS topology table for MAIN_BAS={main_bas}")
    ids = _upstream_basin_ids(rows, seed_id)

    upstream = candidates.filter(ee.Filter.inList("HYBAS_ID", sorted(ids)))
    geom = upstream.union(maxError=120).geometry().simplify(300)
    out = ee.Dictionary({"geom": geom, "area_m2": geom.area(maxError=300)}).getInfo()
    if not out or out.get("geom") is None or out.get("area_m2") is None:
        raise GeeExtractionError(f"catchment union/area evaluation returned null at ({lon}, {lat})")
    area_km2 = float(out["area_m2"]) / 1e6
    if expected_km2:
        ratio = area_km2 / expected_km2
        msg = (
            f"catchment at ({lon}, {lat}): {len(ids)} basins, {area_km2:,.0f} km² "
            f"(expected ≈ {expected_km2:,.0f} km², ratio {ratio:.2f})"
        )
        if 0.8 <= ratio <= 1.2:
            log.info(msg)
        else:
            log.warning("%s — outside ±20%%, check level/seed basin", msg)
    else:
        log.info("catchment at (%s, %s): %d basins, %.0f km²", lon, lat, len(ids), area_km2)
    return out["geom"]


@_gee_retry
def latest_water_extent(
    aoi_geojson: dict,
    *,
    orbit_relative: int | None = None,
    pass_direction: str | None = None,
    smoothing_radius_m: float = 50.0,
) -> dict | None:
    """Most-recent Sentinel-1 VH water mask over the AOI with a **per-scene adaptive
    threshold** (ADR-0007): the VH histogram is reduced server-side, pulled client-side,
    and cut with the shared Otsu-on-histogram implementation from ``extractors``.

    - Scenes are filtered to the reservoir's frozen ``orbit_relative``/``pass_direction``
      (pass values from reservoir config) and must **fully cover** the AOI
      (footprint-contains, not mere ``filterBounds`` intersection).
    - Returns ``None`` (abstain) when the histogram shows no credible water/land
      bimodality — callers must skip the DB write, never record a made-up area.
    - Raises :class:`SceneUnavailableError` / :class:`GeeExtractionError` when no scene
      qualifies or a reduction returns null — a failure is never coerced to 0 km².
    """
    import ee

    init_ee()
    aoi = ee.Geometry(aoi_geojson)
    coll = (
        ee.ImageCollection(S1_GRD)
        .filterBounds(aoi)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
    )
    if orbit_relative is not None:
        coll = coll.filter(ee.Filter.eq("relativeOrbitNumber_start", int(orbit_relative)))
    if pass_direction is not None:
        gee_pass = {"ASC": "ASCENDING", "DESC": "DESCENDING"}.get(
            pass_direction.upper(), pass_direction.upper()
        )
        coll = coll.filter(ee.Filter.eq("orbitProperties_pass", gee_pass))
    # Full-coverage gate: filterBounds is intersects-only; a partial scene would silently
    # truncate the reservoir, so require the scene footprint to contain the whole AOI.
    coll = coll.filter(ee.Filter.contains(leftField=".geo", rightValue=aoi)).sort(
        "system:time_start", False
    )
    if int(coll.size().getInfo() or 0) == 0:
        raise SceneUnavailableError(
            f"no S1 IW/VH scene fully covering the AOI "
            f"(orbit_relative={orbit_relative}, pass_direction={pass_direction})"
        )
    latest = ee.Image(coll.first())
    native_proj = latest.select("VH").projection()
    # Smooth a touch to reduce speckle before histogramming/thresholding.
    vh = latest.select("VH").focal_median(smoothing_radius_m, "circle", "meters")

    # One round-trip: scene metadata + acquisition date + server-side VH histogram.
    bundle = ee.Dictionary(
        {
            "props": latest.toDictionary(
                ["system:index", "relativeOrbitNumber_start", "orbitProperties_pass"]
            ),
            "date": ee.Date(latest.get("system:time_start")).format("YYYY-MM-dd"),
            "hist": vh.reduceRegion(
                reducer=ee.Reducer.histogram(maxBuckets=256),
                geometry=aoi,
                scale=_HIST_SCALE_M,
                crs=native_proj,
                maxPixels=int(1e10),
            ).get("VH"),
        }
    ).getInfo()
    if not bundle:
        raise GeeExtractionError("scene metadata/histogram request returned null")
    hist = bundle.get("hist") or {}
    counts = hist.get("histogram")
    centers = hist.get("bucketMeans")
    if not counts or not centers:
        raise GeeExtractionError("VH histogram reduction returned no data over the AOI")

    # Per-scene adaptive threshold: shared Otsu implementation on the pulled histogram.
    threshold, eta = otsu_from_histogram(counts, centers)
    vr = valley_ratio(counts, centers, threshold)
    sep = fisher_from_histogram(counts, centers, threshold)
    props = bundle["props"]
    scene_id = str(props.get("system:index"))
    processing = {
        "threshold_db": threshold,
        "threshold_method": "otsu_histogram",
        "otsu_eta": eta,
        "valley_ratio": vr,
        "separability": sep,
        "extractor": OtsuVH.name,
        "extractor_version": OtsuVH.version,
        "smoothing_radius_m": smoothing_radius_m,
        "histogram_scale_m": _HIST_SCALE_M,
        "area_scale_m": _AREA_SCALE_M,
        "area_crs": "scene-native projection",
        "coverage_filter": "footprint contains AOI",
        "source": "gee_s1_vh",
    }
    if vr > VALLEY_RATIO_MAX or sep < SEPARABILITY_FLOOR:
        # Bimodality/abstain gate (ADR-0007): unimodal or wind-merged VH histogram means
        # any threshold is an artefact — no confident water mask for this scene.
        log.warning(
            "abstain on scene %s: VH histogram not bimodal "
            "(valley_ratio=%.2f > %.2f or separability=%.2f < %.2f)",
            scene_id,
            vr,
            VALLEY_RATIO_MAX,
            sep,
            SEPARABILITY_FLOOR,
        )
        return None

    water = vh.lt(threshold).selfMask().clip(aoi)
    # True area pinned at the native 10 m scale in the scene CRS — no bestEffort, so a
    # silent scale degradation cannot skew the km² (pixelArea-multiply-then-sum kept).
    area_number = (
        water.multiply(ee.Image.pixelArea())
        .reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=aoi,
            scale=_AREA_SCALE_M,
            crs=native_proj,
            maxPixels=int(1e10),
        )
        .get("VH")
    )
    # Vectorise coarsely (90 m) for the map overlay only; area comes from the reduction.
    geom_obj = (
        water.reduceToVectors(
            geometry=aoi, scale=90, maxPixels=int(1e10), bestEffort=True, geometryType="polygon"
        )
        .geometry()
        .simplify(90)
    )
    out = ee.Dictionary({"area_m2": area_number, "geom": geom_obj}).getInfo() or {}
    area_m2 = out.get("area_m2")
    if area_m2 is None or out.get("geom") is None:
        # A failed/empty reduction must NOT become "0 km² of water".
        raise GeeExtractionError(
            f"area/vector reduction returned null for scene {scene_id}; refusing to record 0 km²"
        )
    return {
        "geojson": out["geom"],
        "area_km2": float(area_m2) / 1e6,
        "acquisition_date": bundle["date"],
        "scene_id": scene_id,
        "orbit_relative": int(props.get("relativeOrbitNumber_start") or 0),
        "pass_direction": "ASC" if props.get("orbitProperties_pass") == "ASCENDING" else "DESC",
        "separability": sep,
        "threshold_db": threshold,
        "processing": processing,
    }
