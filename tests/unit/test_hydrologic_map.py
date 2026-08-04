from __future__ import annotations

import pytest
from remote_sensing.hydrologic_map import prepare_subbasin_topology, resolution_spec


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
            {"hybas_id": 2, "next_down": 1},
            {"hybas_id": 2, "next_down": 1},
        ]
    )

    assert "missing_downstream" in topology.quality_flags
    assert "duplicate_hybas_id" in topology.quality_flags
    by_id = {basin.hybas_id: basin for basin in topology.subbasins}
    assert "missing_downstream" in by_id[1].quality_flags
    assert "duplicate_hybas_id" in by_id[2].quality_flags


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
