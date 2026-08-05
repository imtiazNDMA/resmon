from __future__ import annotations

import pytest
import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon

from remote_sensing.hydrologic_map import (
    prepare_subbasin_topology,
    resolution_spec,
    reproject_gdf_to_wgs84,
    validate_geometries,
    simplify_geometries,
    compute_geometry_areas_km2,
    clip_subbasins_to_catchment,
    clip_flowlines_to_catchment,
    classify_streams_by_order,
    classify_streams_by_upstream_area,
    compute_subbasin_distance_to_point,
    add_subbasin_summary_attributes,
    compute_flowline_lengths_km,
    add_flowline_summary_attributes,
    compute_geometry_quality_flags,
    add_geometry_quality_flags,
    prepare_hydrologic_map_layers,
)


def test_resolution_policy_names_and_tolerances():
    assert resolution_spec("raw").simplify_tolerance_deg == 0
    assert resolution_spec("web").simplify_tolerance_deg == 0.0001
    assert resolution_spec("export").simplify_tolerance_deg == 0.00005
    with pytest.raises(ValueError):
        resolution_spec("thumbnail")  # type: ignore[arg-type]


def test_prepare_subbasin_topology_derives_headwaters_and_path_lengths():
    topology = prepare_subbasin_topology(
        [
            {"hybas_id": 1, "next_down": 0},
            {"hybas_id": 2, "next_down": 1},
            {"hybas_id": 3, "next_down": 2},
            {"hybas_id": 4, "next_down": 2},
        ]
    )

    assert topology.headwater_ids == frozenset({3, 4})
    assert topology.outlet_ids == frozenset({1})
    by_id = {basin.hybas_id: basin for basin in topology.subbasins}
    assert by_id[1].quality_flags == ("outlet_basin",)
    assert by_id[2].downstream_path_length == 1
    assert by_id[3].downstream_path_length == 2
    assert by_id[4].is_headwater is True


def test_prepare_subbasin_topology_accepts_hydrobasins_uppercase_fields():
    topology = prepare_subbasin_topology(
        [{"HYBAS_ID": 10, "NEXT_DOWN": 0}, {"HYBAS_ID": 20, "NEXT_DOWN": 10}]
    )

    assert topology.headwater_ids == frozenset({20})
    assert topology.subbasins[1].next_down == 10


def test_prepare_subbasin_topology_flags_missing_downstream_and_duplicates():
    topology = prepare_subbasin_topology(
        [
            {"hybas_id": 1, "next_down": 99},
            {"hybas_id": 2, "next_down": 98},
            {"hybas_id": 2, "next_down": 1},
        ]
    )

    assert "missing_downstream" in topology.quality_flags
    assert "duplicate_hybas_id" in topology.quality_flags
    by_id = {basin.hybas_id: basin for basin in topology.subbasins}
    assert "missing_downstream" in by_id[1].quality_flags
    assert "duplicate_hybas_id" in by_id[2].quality_flags


def test_prepare_subbasin_topology_classifies_single_external_link_as_outlet():
    topology = prepare_subbasin_topology(
        [
            {"hybas_id": 1, "next_down": 99},
            {"hybas_id": 2, "next_down": 1},
        ]
    )

    assert topology.outlet_ids == frozenset({1})
    assert "missing_downstream" not in topology.quality_flags
    by_id = {basin.hybas_id: basin for basin in topology.subbasins}
    assert by_id[1].quality_flags == ("outlet_basin", "external_outlet")


def test_prepare_subbasin_topology_flags_cycles():
    topology = prepare_subbasin_topology(
        [
            {"hybas_id": 1, "next_down": 2},
            {"hybas_id": 2, "next_down": 3},
            {"hybas_id": 3, "next_down": 1},
        ]
    )

    assert topology.quality_flags == ("cycle_detected",)
    assert all(basin.downstream_path_length is None for basin in topology.subbasins)


def test_reproject_gdf_to_wgs84_from_utm():
    square = Polygon([(500000, 4000000), (500100, 4000000), (500100, 4000100), (500000, 4000100)])
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[square], crs="EPSG:32633")

    result = reproject_gdf_to_wgs84(gdf)

    assert result.crs.to_epsg() == 4326
    assert len(result) == 1
    assert result.geometry[0].bounds[0] > -180


def test_reproject_gdf_to_wgs84_already_4326():
    square = Polygon([(10, 50), (11, 50), (11, 51), (10, 51)])
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[square], crs="EPSG:4326")

    result = reproject_gdf_to_wgs84(gdf)

    assert result.crs.to_epsg() == 4326
    assert len(result) == 1


def test_reproject_gdf_to_wgs84_raises_on_missing_crs():
    square = Polygon([(10, 50), (11, 50), (11, 51), (10, 51)])
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[square])

    with pytest.raises(ValueError, match="no CRS"):
        reproject_gdf_to_wgs84(gdf)


def test_validate_geometries_removes_invalid():
    valid = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    invalid = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
    empty = Polygon()

    gdf = gpd.GeoDataFrame(
        {"id": [1, 2, 3]}, geometry=[valid, invalid, empty], crs="EPSG:4326"
    )

    result = validate_geometries(gdf)

    assert len(result) >= 1


def test_simplify_geometries_preserves_topology():
    complex_poly = Polygon([(0, 0), (0.00001, 0), (0.00002, 0.00001), (0, 0.00001)])
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[complex_poly], crs="EPSG:4326")

    result = simplify_geometries(gdf, tolerance_deg=0.0001)

    assert len(result) == 1
    assert result.geometry[0].is_valid


def test_simplify_geometries_zero_tolerance():
    poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[poly], crs="EPSG:4326")

    result = simplify_geometries(gdf, tolerance_deg=0)

    assert len(result) == 1
    assert result.geometry[0].equals(poly)


def test_compute_geometry_areas_km2():
    square = Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01)])
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[square], crs="EPSG:4326")

    areas = compute_geometry_areas_km2(gdf)

    assert len(areas) == 1
    assert areas[0] > 0
    assert areas[0] < 200


def test_clip_subbasins_to_catchment():
    catchment = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    subbasin1 = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    subbasin2 = Polygon([(1, 0), (2, 0), (2, 1), (1, 1)])
    subbasin3 = Polygon([(3, 0), (4, 0), (4, 1), (3, 1)])

    gdf = gpd.GeoDataFrame(
        {"hybas_id": [1, 2, 3], "next_down": [0, 1, 0]},
        geometry=[subbasin1, subbasin2, subbasin3],
        crs="EPSG:4326",
    )

    result = clip_subbasins_to_catchment(gdf, catchment)

    assert len(result) == 2
    assert "hybas_id" in result.columns
    assert "next_down" in result.columns


def test_clip_flowlines_to_catchment():
    catchment = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    from shapely.geometry import LineString

    line1 = LineString([(0.5, 0.5), (1.5, 1.5)])
    line2 = LineString([(3, 0.5), (4, 1.5)])

    gdf = gpd.GeoDataFrame(
        {"stream_order": [1, 2], "upstream_area_km2": [10, 50]},
        geometry=[line1, line2],
        crs="EPSG:4326",
    )

    result = clip_flowlines_to_catchment(gdf, catchment)

    assert len(result) == 1
    assert "stream_order" in result.columns


def test_classify_streams_by_order_with_stream_order_column():
    from shapely.geometry import LineString

    line1 = LineString([(0, 0), (1, 1)])
    line2 = LineString([(1, 1), (2, 2)])

    gdf = gpd.GeoDataFrame(
        {"stream_order": [1, 2]}, geometry=[line1, line2], crs="EPSG:4326"
    )

    result = classify_streams_by_order(gdf)

    assert "stream_order" in result.columns
    assert result["stream_order"].tolist() == [1, 2]


def test_classify_streams_by_order_with_ORDER_column():
    from shapely.geometry import LineString

    line1 = LineString([(0, 0), (1, 1)])
    line2 = LineString([(1, 1), (2, 2)])

    gdf = gpd.GeoDataFrame({"ORDER": [1, 2]}, geometry=[line1, line2], crs="EPSG:4326")

    result = classify_streams_by_order(gdf)

    assert "stream_order" in result.columns
    assert result["stream_order"].tolist() == [1, 2]


def test_classify_streams_by_upstream_area():
    from shapely.geometry import LineString

    line1 = LineString([(0, 0), (1, 1)])
    line2 = LineString([(1, 1), (2, 2)])
    line3 = LineString([(2, 2), (3, 3)])

    gdf = gpd.GeoDataFrame(
        {"upstream_area_km2": [50, 200, 600]},
        geometry=[line1, line2, line3],
        crs="EPSG:4326",
    )

    result = classify_streams_by_upstream_area(gdf, threshold_km2=100)

    assert "stream_classification" in result.columns
    assert result["stream_classification"].tolist() == ["headwater", "tributary", "main_stem"]


def test_compute_subbasin_distance_to_point():
    subbasin1 = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    subbasin2 = Polygon([(2, 2), (3, 2), (3, 3), (2, 3)])

    gdf = gpd.GeoDataFrame(
        {"id": [1, 2]}, geometry=[subbasin1, subbasin2], crs="EPSG:4326"
    )

    target = Point(0, 0)
    distances = compute_subbasin_distance_to_point(gdf, target)

    assert len(distances) == 2
    assert distances[0] == 0
    assert distances[1] > distances[0]


def test_add_subbasin_summary_attributes():
    subbasin1 = Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01)])
    subbasin2 = Polygon([(1, 1), (1.01, 1), (1.01, 1.01), (1, 1.01)])

    gdf = gpd.GeoDataFrame(
        {"hybas_id": [1, 2]}, geometry=[subbasin1, subbasin2], crs="EPSG:4326"
    )

    result = add_subbasin_summary_attributes(gdf)

    assert "area_km2" in result.columns
    assert "centroid_lon" in result.columns
    assert "centroid_lat" in result.columns
    assert len(result) == 2
    assert result["area_km2"][0] > 0
    assert result["centroid_lon"][0] < 0.01


def test_compute_flowline_lengths_km():
    from shapely.geometry import LineString

    line1 = LineString([(0, 0), (0.01, 0.01)])
    line2 = LineString([(1, 1), (1.1, 1.1)])

    gdf = gpd.GeoDataFrame({"id": [1, 2]}, geometry=[line1, line2], crs="EPSG:4326")

    lengths = compute_flowline_lengths_km(gdf)

    assert len(lengths) == 2
    assert all(length > 0 for length in lengths)
    assert lengths[1] > lengths[0]


def test_add_flowline_summary_attributes():
    from shapely.geometry import LineString

    line1 = LineString([(0, 0), (0.01, 0.01)])
    line2 = LineString([(1, 1), (1.1, 1.1)])

    gdf = gpd.GeoDataFrame(
        {"stream_classification": ["headwater", "main_stem"]},
        geometry=[line1, line2],
        crs="EPSG:4326",
    )

    result = add_flowline_summary_attributes(gdf)

    assert "length_km" in result.columns
    assert "is_main_stem" in result.columns
    assert result["is_main_stem"][0] == False
    assert result["is_main_stem"][1] == True


def test_compute_geometry_quality_flags_detects_empty():
    valid = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    empty = Polygon()

    gdf = gpd.GeoDataFrame({"id": [1, 2]}, geometry=[valid, empty], crs="EPSG:4326")

    flags = compute_geometry_quality_flags(gdf)

    assert len(flags) == 2
    assert len(flags[0]) == 0
    assert "empty_geometry" in flags[1]


def test_add_geometry_quality_flags():
    valid = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    invalid = Polygon([(0, 0), (2, 2), (2, 0), (0, 2)])

    gdf = gpd.GeoDataFrame(
        {"id": [1, 2]}, geometry=[valid, invalid], crs="EPSG:4326"
    )

    result = add_geometry_quality_flags(gdf)

    assert "quality_flags" in result.columns
    assert len(result) == 2
    assert isinstance(result["quality_flags"][0], tuple)


def test_prepare_hydrologic_map_layers_orchestrates_vector_prep():
    catchment = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    dam_point = Point(1.9, 0.1)
    subbasins = gpd.GeoDataFrame(
        {"HYBAS_ID": [1, 2], "NEXT_DOWN": [0, 1]},
        geometry=[
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
        ],
        crs="EPSG:4326",
    )
    flowlines = gpd.GeoDataFrame(
        {"HYRIV_ID": [10], "NEXT_DOWN": [0], "ORDER": [2], "UPLAND_SKM": [250.0]},
        geometry=[LineString([(0.2, 0.2), (1.8, 0.2)])],
        crs="EPSG:4326",
    )

    prepared = prepare_hydrologic_map_layers(
        catchment_geom=catchment,
        subbasins_gdf=subbasins,
        flowlines_gdf=flowlines,
        dam_point=dam_point,
    )

    assert set(prepared.subbasins) == {"raw", "web", "export"}
    web_subbasins = prepared.subbasins["web"]
    assert web_subbasins.crs.to_epsg() == 4326
    assert web_subbasins["hybas_id"].tolist() == [1, 2]
    assert web_subbasins["is_headwater"].tolist() == [False, True]
    assert "area_km2" in web_subbasins.columns
    assert "distance_to_reservoir_km" in web_subbasins.columns
    assert "outlet_basin" in web_subbasins["quality_flags"][0]

    web_flowlines = prepared.flowlines["web"]
    assert web_flowlines["flowline_id"].tolist() == [10]
    assert web_flowlines["stream_order"].tolist() == [2]
    assert web_flowlines["upstream_area_km2"].tolist() == [250.0]
    assert web_flowlines["length_km"][0] > 0
    assert web_flowlines["is_main_stem"].tolist() == [False]
