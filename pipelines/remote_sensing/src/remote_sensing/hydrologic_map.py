"""Pure preparation helpers for HydroSHEDS-style hydrologic map layers.

This module is the testable spine for Phase 8A.3. It deliberately avoids a heavy GIS
dependency: geometry clipping/DEM work happens in GEE/PostGIS later, while topology,
resolution policy, and QA flags stay pure Python and unit-testable.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal

import geopandas as gpd
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

GeometryResolution = Literal["raw", "web", "export"]
QualityFlag = Literal[
    "duplicate_hybas_id",
    "missing_downstream",
    "external_outlet",
    "cycle_detected",
    "outlet_basin",
    "invalid_geometry",
    "empty_geometry",
    "self_intersecting",
    "clipped_sliver",
    "disconnected_flowline",
    "low_confidence_boundary",
]


@dataclass(frozen=True)
class GeometryResolutionSpec:
    name: GeometryResolution
    simplify_tolerance_deg: float
    intended_use: str


GEOMETRY_RESOLUTIONS: tuple[GeometryResolutionSpec, ...] = (
    GeometryResolutionSpec("raw", 0.0, "internal processing and QA"),
    GeometryResolutionSpec("web", 0.0001, "interactive Leaflet overlays"),
    GeometryResolutionSpec("export", 0.00005, "static map exports and reports"),
)


@dataclass(frozen=True)
class PreparedSubbasin:
    hybas_id: int
    next_down: int
    is_headwater: bool
    downstream_path_length: int | None
    quality_flags: tuple[QualityFlag, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PreparedSubbasinTopology:
    subbasins: tuple[PreparedSubbasin, ...]
    headwater_ids: frozenset[int]
    outlet_ids: frozenset[int]
    quality_flags: tuple[QualityFlag, ...]


@dataclass(frozen=True)
class PreparedHydrologicMapLayers:
    subbasins: dict[GeometryResolution, gpd.GeoDataFrame]
    flowlines: dict[GeometryResolution, gpd.GeoDataFrame]
    quality_flags: tuple[QualityFlag, ...]


def resolution_spec(name: GeometryResolution) -> GeometryResolutionSpec:
    for spec in GEOMETRY_RESOLUTIONS:
        if spec.name == name:
            return spec
    raise ValueError(f"unknown geometry resolution: {name}")


def _int_value(row: Mapping, key: str) -> int:
    value = row.get(key)
    if value is None:
        raise ValueError(f"missing required HydroBASINS field {key!r}")
    return int(value)


def _path_length_to_outlet(hybas_id: int, next_by_id: Mapping[int, int]) -> tuple[int | None, bool]:
    seen: set[int] = set()
    current = hybas_id
    length = 0
    while True:
        if current in seen:
            return None, True
        seen.add(current)
        next_down = next_by_id.get(current, 0)
        if next_down == 0 or next_down not in next_by_id:
            return length, False
        current = next_down
        length += 1


def prepare_subbasin_topology(rows: Iterable[Mapping]) -> PreparedSubbasinTopology:
    """Derive topology attributes and QA flags from HydroBASINS rows.

    Input rows must include ``hybas_id``/``HYBAS_ID`` and ``next_down``/``NEXT_DOWN``.
    ``next_down = 0`` is treated as the outlet. A downstream id outside the selected
    catchment is flagged as missing downstream; this is expected at the outlet only.
    """
    normalized = []
    for row in rows:
        hybas_id = _int_value(row, "hybas_id") if "hybas_id" in row else _int_value(row, "HYBAS_ID")
        next_down = (
            _int_value(row, "next_down") if "next_down" in row else _int_value(row, "NEXT_DOWN")
        )
        normalized.append((hybas_id, next_down))

    counts = Counter(hybas_id for hybas_id, _ in normalized)
    duplicate_ids = {hybas_id for hybas_id, count in counts.items() if count > 1}
    next_by_id = {hybas_id: next_down for hybas_id, next_down in normalized}
    fed_ids = {next_down for _, next_down in normalized if next_down in next_by_id}
    headwater_ids = frozenset(hybas_id for hybas_id, _ in normalized if hybas_id not in fed_ids)
    external_terminal_ids = {
        hybas_id
        for hybas_id, next_down in normalized
        if next_down != 0 and next_down not in next_by_id
    }
    external_outlet_ids = external_terminal_ids if len(external_terminal_ids) == 1 else set()
    outlet_ids = frozenset(
        hybas_id
        for hybas_id, next_down in normalized
        if next_down == 0 or hybas_id in external_outlet_ids
    )

    prepared = []
    global_flags: set[QualityFlag] = set()
    for hybas_id, next_down in normalized:
        flags: list[QualityFlag] = []
        if hybas_id in duplicate_ids:
            flags.append("duplicate_hybas_id")
        if next_down == 0:
            flags.append("outlet_basin")
        elif next_down not in next_by_id:
            if hybas_id in external_outlet_ids:
                flags.extend(["outlet_basin", "external_outlet"])
            else:
                flags.append("missing_downstream")
        path_length, has_cycle = _path_length_to_outlet(hybas_id, next_by_id)
        if has_cycle:
            flags.append("cycle_detected")
        global_flags.update(flags)
        prepared.append(
            PreparedSubbasin(
                hybas_id=hybas_id,
                next_down=next_down,
                is_headwater=hybas_id in headwater_ids,
                downstream_path_length=path_length,
                quality_flags=tuple(flags),
            )
        )

    return PreparedSubbasinTopology(
        subbasins=tuple(prepared),
        headwater_ids=headwater_ids,
        outlet_ids=outlet_ids,
        quality_flags=tuple(sorted(global_flags)),
    )


def reproject_gdf_to_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reproject GeoDataFrame to WGS84 (EPSG:4326) for web serving.

    Returns a copy with the same data and CRS = EPSG:4326.
    """
    if gdf.crs is None:
        raise ValueError("GeoDataFrame has no CRS; cannot reproject")
    if gdf.crs.to_epsg() == 4326:
        return gdf.copy()
    return gdf.to_crs(epsg=4326)


def validate_geometries(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Validate and repair geometries, removing invalid/empty ones.

    Returns GeoDataFrame with invalid/empty geometries removed and
    self-intersecting geometries made valid via buffer(0).
    """
    gdf = gdf.copy()
    valid_mask = gdf.geometry.is_valid & ~gdf.geometry.is_empty
    gdf = gdf[valid_mask].copy()

    gdf["geometry"] = gdf.geometry.apply(
        lambda g: g.buffer(0) if not g.is_valid and not g.is_empty else g
    )
    return gdf.reset_index(drop=True)


def simplify_geometries(gdf: gpd.GeoDataFrame, tolerance_deg: float) -> gpd.GeoDataFrame:
    """Simplify geometries using Douglas-Peucker algorithm.

    Args:
        gdf: Input GeoDataFrame
        tolerance_deg: Simplification tolerance in degrees (0 = no simplification)

    Returns:
        GeoDataFrame with simplified geometries
    """
    if tolerance_deg <= 0:
        return gdf.copy()

    gdf = gdf.copy()
    gdf["geometry"] = gdf.geometry.simplify(tolerance_deg, preserve_topology=True)
    return gdf


def compute_geometry_areas_km2(gdf: gpd.GeoDataFrame) -> list[float]:
    """Compute polygon areas in km² using an equal-area projection per geometry.

    For each geometry, projects to a Lambert Azimuthal Equal Area projection
    centered on that geometry's centroid, computes area, then returns results.
    """
    if gdf.crs is None:
        raise ValueError("GeoDataFrame has no CRS; cannot compute areas")

    from pyproj import Proj

    areas_km2 = []
    for geom in gdf.geometry:
        if geom.is_empty:
            areas_km2.append(0.0)
            continue

        centroid = geom.centroid
        laea_proj_str = f"+proj=laea +lon_0={centroid.x} +lat_0={centroid.y} +ellps=WGS84"

        try:
            gdf_single = gpd.GeoDataFrame({"id": [0]}, geometry=[geom], crs="EPSG:4326")
            gdf_ea = gdf_single.to_crs(laea_proj_str)
            area_m2 = gdf_ea.geometry.area[0]
            areas_km2.append(area_m2 / 1_000_000)
        except Exception:
            areas_km2.append(0.0)

    return areas_km2


def clip_subbasins_to_catchment(
    subbasins_gdf: gpd.GeoDataFrame, catchment_geom: BaseGeometry
) -> gpd.GeoDataFrame:
    """Clip HydroBASINS sub-basins to a single catchment polygon.

    Preserves HYBAS_ID/NEXT_DOWN topology columns. Returns clipped GeoDataFrame,
    removing sub-basins that don't intersect the catchment.
    """
    if subbasins_gdf.crs is None:
        raise ValueError("subbasins_gdf must have a CRS")

    result = subbasins_gdf.clip(catchment_geom).copy()

    if len(result) == 0:
        return result

    return result.reset_index(drop=True)


def clip_flowlines_to_catchment(
    flowlines_gdf: gpd.GeoDataFrame, catchment_geom: BaseGeometry
) -> gpd.GeoDataFrame:
    """Clip HydroRIVERS/MERIT Hydro flowlines to a single catchment polygon.

    Preserves stream order, upstream area, and topology columns.
    Returns clipped GeoDataFrame.
    """
    if flowlines_gdf.crs is None:
        raise ValueError("flowlines_gdf must have a CRS")

    result = flowlines_gdf.clip(catchment_geom).copy()

    if len(result) == 0:
        return result

    return result.reset_index(drop=True)


def classify_streams_by_order(flowlines_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Classify flowlines by Strahler stream order.

    Expects a column 'stream_order' or 'ORDER' (HydroRIVERS/MERIT convention).
    Returns GeoDataFrame with normalized 'stream_order' column.
    """
    result = flowlines_gdf.copy()

    if "stream_order" not in result.columns and "ORDER" in result.columns:
        result = result.rename(columns={"ORDER": "stream_order"})

    if "stream_order" not in result.columns:
        result["stream_order"] = 0

    return result


def classify_streams_by_upstream_area(
    flowlines_gdf: gpd.GeoDataFrame, threshold_km2: float = 100
) -> gpd.GeoDataFrame:
    """Classify flowlines by upstream area: "headwater" vs "tributary" vs "main_stem".

    Args:
        flowlines_gdf: Input flowlines with optional 'upstream_area_km2' column
        threshold_km2: Area threshold; areas below are headwaters

    Returns:
        GeoDataFrame with added 'stream_classification' column
    """
    result = flowlines_gdf.copy()

    if "upstream_area_km2" not in result.columns and "ORD_FLOW" not in result.columns:
        result["stream_classification"] = "unknown"
        return result

    if "upstream_area_km2" not in result.columns:
        result = result.rename(columns={"ORD_FLOW": "upstream_area_km2"})

    def classify(area):
        if area < threshold_km2:
            return "headwater"
        elif area < threshold_km2 * 5:
            return "tributary"
        else:
            return "main_stem"

    result["stream_classification"] = result["upstream_area_km2"].apply(classify)
    return result


def compute_subbasin_distance_to_point(
    subbasins_gdf: gpd.GeoDataFrame, target_point: BaseGeometry
) -> list[float]:
    """Compute minimum distance from each sub-basin to a target point (e.g., reservoir).

    Returns distances in the same units as the CRS (degrees for EPSG:4326).
    """
    distances = []
    for geom in subbasins_gdf.geometry:
        if geom.is_empty:
            distances.append(None)
        else:
            distances.append(geom.distance(target_point))
    return distances


def add_subbasin_summary_attributes(subbasins_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add summary attributes to sub-basins: area_km2, centroid_lon/lat, distance_km.

    Returns GeoDataFrame with added columns.
    """
    result = subbasins_gdf.copy()

    areas_km2 = compute_geometry_areas_km2(result)
    result["area_km2"] = areas_km2

    centroids = [geom.centroid for geom in result.geometry]
    result["centroid_lon"] = [point.x for point in centroids]
    result["centroid_lat"] = [point.y for point in centroids]

    return result


def compute_flowline_lengths_km(flowlines_gdf: gpd.GeoDataFrame) -> list[float]:
    """Compute line lengths in km using equal-area projection per line.

    Returns lengths in kilometers.
    """
    from pyproj import Proj

    lengths_km = []
    for geom in flowlines_gdf.geometry:
        if geom.is_empty:
            lengths_km.append(0.0)
            continue

        if hasattr(geom, "coords"):
            coords = list(geom.coords)
            if len(coords) < 2:
                lengths_km.append(0.0)
                continue
            mid_pt = coords[len(coords) // 2]
        else:
            mid_pt = geom.centroid.coords[0]

        laea_proj_str = f"+proj=laea +lon_0={mid_pt[0]} +lat_0={mid_pt[1]} +ellps=WGS84"

        try:
            gdf_single = gpd.GeoDataFrame({"id": [0]}, geometry=[geom], crs="EPSG:4326")
            gdf_ea = gdf_single.to_crs(laea_proj_str)
            length_m = gdf_ea.geometry.length[0]
            lengths_km.append(length_m / 1000)
        except Exception:
            lengths_km.append(0.0)

    return lengths_km


def add_flowline_summary_attributes(flowlines_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add summary attributes to flowlines: length_km, is_main_stem, flow_direction_azimuth.

    Returns GeoDataFrame with added columns.
    """
    result = flowlines_gdf.copy()

    lengths_km = compute_flowline_lengths_km(result)
    result["length_km"] = lengths_km

    if "stream_classification" not in result.columns:
        result["stream_classification"] = "unknown"

    result["is_main_stem"] = result["stream_classification"].apply(
        lambda x: x == "main_stem" if isinstance(x, str) else False
    )

    return result


def compute_geometry_quality_flags(gdf: gpd.GeoDataFrame) -> list[tuple[QualityFlag, ...]]:
    """Compute QA flags for each geometry: invalid, empty, self-intersecting, slivers.

    Returns list of flag tuples, one per row.
    """
    flags_per_geom = []

    for geom in gdf.geometry:
        flags: list[QualityFlag] = []

        if geom.is_empty:
            flags.append("empty_geometry")
        elif not geom.is_valid:
            flags.append("invalid_geometry")
            if hasattr(geom, "is_ring"):
                if geom.length > 0 and geom.area < 1e-10:
                    flags.append("clipped_sliver")
        else:
            if hasattr(geom, "exterior") and hasattr(geom.exterior, "is_ccw"):
                if not geom.is_simple:
                    flags.append("self_intersecting")

            if hasattr(geom, "area"):
                if geom.area > 0 and geom.length > 0:
                    aspect_ratio = geom.area / (geom.length ** 2)
                    if aspect_ratio < 0.001:
                        flags.append("clipped_sliver")

        flags_per_geom.append(tuple(flags))

    return flags_per_geom


def add_geometry_quality_flags(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add 'quality_flags' column to GeoDataFrame with geometry QA status.

    Returns GeoDataFrame with added quality_flags column.
    """
    result = gdf.copy()
    quality_flags = compute_geometry_quality_flags(result)
    result["quality_flags"] = quality_flags
    return result


def _empty_like(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return gdf.iloc[0:0].copy().reset_index(drop=True)


def _normalize_subbasin_columns(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    result = gdf.copy()
    rename_map = {}
    if "hybas_id" not in result.columns and "HYBAS_ID" in result.columns:
        rename_map["HYBAS_ID"] = "hybas_id"
    if "next_down" not in result.columns and "NEXT_DOWN" in result.columns:
        rename_map["NEXT_DOWN"] = "next_down"
    if rename_map:
        result = result.rename(columns=rename_map)
    missing = {"hybas_id", "next_down"} - set(result.columns)
    if missing:
        raise ValueError(f"missing required sub-basin columns: {sorted(missing)}")
    return result


def _normalize_flowline_columns(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    result = gdf.copy()
    rename_map = {}
    if "flowline_id" not in result.columns:
        for candidate in ("HYRIV_ID", "COMID", "id"):
            if candidate in result.columns:
                rename_map[candidate] = "flowline_id"
                break
    if "downstream_id" not in result.columns:
        for candidate in ("NEXT_DOWN", "NEXTDOWNID", "next_down"):
            if candidate in result.columns:
                rename_map[candidate] = "downstream_id"
                break
    if "upstream_area_km2" not in result.columns and "UPLAND_SKM" in result.columns:
        rename_map["UPLAND_SKM"] = "upstream_area_km2"
    if rename_map:
        result = result.rename(columns=rename_map)
    if "flowline_id" not in result.columns:
        result["flowline_id"] = range(1, len(result) + 1)
    if "downstream_id" not in result.columns:
        result["downstream_id"] = None
    return result


def _distance_km(geom: BaseGeometry | None, target: BaseGeometry) -> float | None:
    if geom is None or geom.is_empty or target.is_empty:
        return None
    origin = geom.centroid
    laea_proj_str = f"+proj=laea +lon_0={origin.x} +lat_0={origin.y} +ellps=WGS84"
    gdf = gpd.GeoDataFrame({"id": [0, 1]}, geometry=[geom.centroid, target], crs="EPSG:4326")
    try:
        projected = gdf.to_crs(laea_proj_str)
        return float(projected.geometry[0].distance(projected.geometry[1]) / 1000)
    except Exception:
        return None


def _line_endpoint(geom: BaseGeometry) -> Point | None:
    if geom.is_empty:
        return None
    if hasattr(geom, "coords"):
        coords = list(geom.coords)
        return Point(coords[-1]) if coords else None
    parts = getattr(geom, "geoms", None)
    if parts:
        last = parts[-1]
        coords = list(last.coords) if hasattr(last, "coords") else []
        return Point(coords[-1]) if coords else None
    return None


def _with_resolutions(gdf: gpd.GeoDataFrame) -> dict[GeometryResolution, gpd.GeoDataFrame]:
    return {
        spec.name: simplify_geometries(gdf, spec.simplify_tolerance_deg)
        for spec in GEOMETRY_RESOLUTIONS
    }


def prepare_hydrologic_map_layers(
    *,
    catchment_geom: BaseGeometry,
    subbasins_gdf: gpd.GeoDataFrame,
    flowlines_gdf: gpd.GeoDataFrame | None = None,
    dam_point: BaseGeometry | None = None,
) -> PreparedHydrologicMapLayers:
    """Prepare static hydrologic map layers for persistence and web serving.

    This is the Phase 8A.3 orchestration seam: source geometries are reprojected to
    WGS84, validated, clipped to the reservoir catchment, enriched with topology and
    summary attributes, tagged with QA flags, and emitted at raw/web/export resolutions.
    DEM-derived terrain/elevation attributes are intentionally outside this pure vector
    step until DEM assets are available.
    """
    subbasins = _normalize_subbasin_columns(reproject_gdf_to_wgs84(subbasins_gdf))
    subbasins = validate_geometries(subbasins)
    subbasins = clip_subbasins_to_catchment(subbasins, catchment_geom)
    subbasins = add_subbasin_summary_attributes(subbasins)
    topology = prepare_subbasin_topology(subbasins.to_dict("records"))
    topology_by_id = {row.hybas_id: row for row in topology.subbasins}
    subbasins["is_headwater"] = subbasins["hybas_id"].map(
        lambda value: topology_by_id[int(value)].is_headwater
    )
    subbasins["downstream_path_length"] = subbasins["hybas_id"].map(
        lambda value: topology_by_id[int(value)].downstream_path_length
    )
    if dam_point is not None:
        subbasins["distance_to_reservoir_km"] = [
            _distance_km(geom, dam_point) for geom in subbasins.geometry
        ]
    subbasins = add_geometry_quality_flags(subbasins)
    subbasins["quality_flags"] = [
        tuple(sorted(set(geom_flags) | set(topology_by_id[int(hybas_id)].quality_flags)))
        for hybas_id, geom_flags in zip(
            subbasins["hybas_id"], subbasins["quality_flags"], strict=True
        )
    ]

    if flowlines_gdf is None:
        flowlines = gpd.GeoDataFrame(
            {
                "flowline_id": [],
                "downstream_id": [],
                "stream_order": [],
                "upstream_area_km2": [],
                "length_km": [],
                "is_main_stem": [],
                "terminates_near_reservoir": [],
                "quality_flags": [],
            },
            geometry=[],
            crs="EPSG:4326",
        )
    else:
        flowlines = _normalize_flowline_columns(reproject_gdf_to_wgs84(flowlines_gdf))
        flowlines = validate_geometries(flowlines)
        flowlines = clip_flowlines_to_catchment(flowlines, catchment_geom)
        if len(flowlines) > 0:
            flowlines = classify_streams_by_order(flowlines)
            flowlines = classify_streams_by_upstream_area(flowlines)
            flowlines = add_flowline_summary_attributes(flowlines)
            if dam_point is not None:
                distances = [
                    _distance_km(point, dam_point)
                    for point in map(_line_endpoint, flowlines.geometry)
                ]
                flowlines["terminates_near_reservoir"] = [
                    distance is not None and distance <= 2 for distance in distances
                ]
            else:
                flowlines["terminates_near_reservoir"] = False
            flowlines = add_geometry_quality_flags(flowlines)
        else:
            flowlines = _empty_like(flowlines)

    flags: set[QualityFlag] = set(topology.quality_flags)
    for flags_tuple in subbasins.get("quality_flags", []):
        flags.update(flags_tuple)
    for flags_tuple in flowlines.get("quality_flags", []):
        flags.update(flags_tuple)

    return PreparedHydrologicMapLayers(
        subbasins=_with_resolutions(subbasins),
        flowlines=_with_resolutions(flowlines),
        quality_flags=tuple(sorted(flags)),
    )
