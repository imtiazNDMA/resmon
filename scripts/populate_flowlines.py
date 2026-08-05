"""Clip local HydroRIVERS vectors to persisted reservoir catchments.

Requires the HydroRIVERS Asia shapefile at:
    data/HydroRIVERS_v10_as_shp/HydroRIVERS_v10_as_shp/HydroRIVERS_v10_as.shp

Run all pilots:
    uv run python scripts/populate_flowlines.py

Run one reservoir:
    uv run python scripts/populate_flowlines.py --reservoir pong
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from core.db.session import make_engine
from data_engineering.reservoirs import REGISTRY
from remote_sensing.hydrologic_map import (
    add_flowline_summary_attributes,
    classify_streams_by_upstream_area,
    clip_flowlines_to_catchment,
    reproject_gdf_to_wgs84,
    validate_geometries,
)
from shapely import wkb
from shapely.geometry import mapping
from sqlalchemy import text
from sqlalchemy.orm import Session

HYDRORIVERS_PATH = Path(
    "data/HydroRIVERS_v10_as_shp/HydroRIVERS_v10_as_shp/HydroRIVERS_v10_as.shp"
)

_CATCHMENT = text(
    """
    SELECT ST_AsBinary(catchment_geom) AS geom
    FROM reservoir
    WHERE reservoir_id = :reservoir_id AND catchment_geom IS NOT NULL
    """
)

_DELETE_FLOWLINES = text("DELETE FROM catchment_flowline WHERE reservoir_id = :reservoir_id")

_INSERT_FLOWLINE = text(
    """
    INSERT INTO catchment_flowline
      (reservoir_id, flowline_id, downstream_id, stream_order, upstream_area_km2,
       length_km, is_main_stem, geom, source_dataset, version)
    VALUES
      (:reservoir_id, :flowline_id, :downstream_id, :stream_order, :upstream_area_km2,
       :length_km, :is_main_stem, ST_Multi(ST_GeomFromGeoJSON(:geom)),
       'HydroRIVERS', 'v10_as')
    """
)

_UPSERT_PROVENANCE = text(
    """
    INSERT INTO hydrologic_layer_provenance
      (reservoir_id, layer_name, source_dataset, source_version, source_date,
       resolution_m, processed_at, processing_version, simplification_tolerance_deg,
       projection, limitations, metadata_json)
    VALUES
      (:reservoir_id, 'flowlines', 'HydroRIVERS', 'v10_as', NULL,
       500, now(), 'populate_flowlines_v1', 0.0001, 'EPSG:4326',
       :limitations, CAST(:metadata_json AS jsonb))
    ON CONFLICT (reservoir_id, layer_name) DO UPDATE SET
      source_dataset = EXCLUDED.source_dataset,
      source_version = EXCLUDED.source_version,
      resolution_m = EXCLUDED.resolution_m,
      processed_at = EXCLUDED.processed_at,
      processing_version = EXCLUDED.processing_version,
      simplification_tolerance_deg = EXCLUDED.simplification_tolerance_deg,
      projection = EXCLUDED.projection,
      limitations = EXCLUDED.limitations,
      metadata_json = EXCLUDED.metadata_json
    """
)


def _registry_by_slug():
    return {meta.slug: meta for meta in REGISTRY.values()}


def _catchment_geom(session: Session, reservoir_id: str):
    row = session.execute(_CATCHMENT, {"reservoir_id": reservoir_id}).mappings().first()
    if row is None or row["geom"] is None:
        raise ValueError(f"reservoir {reservoir_id!r} has no catchment_geom")
    return wkb.loads(bytes(row["geom"]))


def _load_hydrorivers_for_catchment(catchment_geom) -> gpd.GeoDataFrame:
    if not HYDRORIVERS_PATH.exists():
        raise FileNotFoundError(f"HydroRIVERS shapefile not found: {HYDRORIVERS_PATH}")
    minx, miny, maxx, maxy = catchment_geom.bounds
    rivers = gpd.read_file(HYDRORIVERS_PATH, bbox=(minx, miny, maxx, maxy))
    return reproject_gdf_to_wgs84(rivers)


def _prepare_flowlines(catchment_geom) -> gpd.GeoDataFrame:
    rivers = _load_hydrorivers_for_catchment(catchment_geom)
    if len(rivers) == 0:
        return rivers

    rivers = rivers.rename(
        columns={
            "HYRIV_ID": "flowline_id",
            "NEXT_DOWN": "downstream_id",
            "ORD_STRA": "stream_order",
            "UPLAND_SKM": "upstream_area_km2",
        }
    )
    rivers = validate_geometries(rivers)
    clipped = clip_flowlines_to_catchment(rivers, catchment_geom)
    if len(clipped) == 0:
        return clipped
    clipped = classify_streams_by_upstream_area(clipped)
    clipped = add_flowline_summary_attributes(clipped)
    clipped["downstream_id"] = clipped["downstream_id"].where(clipped["downstream_id"] != 0, None)
    return clipped


def _int_or_none(value) -> int | None:
    return None if pd.isna(value) else int(value)


def _float_or_none(value) -> float | None:
    return None if pd.isna(value) else float(value)


def populate_flowlines_for_reservoir(session: Session, reservoir_id: str) -> int:
    catchment_geom = _catchment_geom(session, reservoir_id)
    flowlines = _prepare_flowlines(catchment_geom)

    session.execute(_DELETE_FLOWLINES, {"reservoir_id": reservoir_id})
    for row in flowlines.itertuples(index=False):
        session.execute(
            _INSERT_FLOWLINE,
            {
                "reservoir_id": reservoir_id,
                "flowline_id": int(row.flowline_id),
                "downstream_id": _int_or_none(row.downstream_id),
                "stream_order": _int_or_none(row.stream_order),
                "upstream_area_km2": _float_or_none(row.upstream_area_km2),
                "length_km": _float_or_none(row.length_km),
                "is_main_stem": bool(row.is_main_stem),
                "geom": json.dumps(mapping(row.geometry)),
            },
        )
    session.execute(
        _UPSERT_PROVENANCE,
        {
            "reservoir_id": reservoir_id,
            "limitations": (
                "HydroRIVERS vectors are clipped to HydroBASINS-derived catchments; "
                "line direction and downstream ids are inherited from HydroRIVERS and "
                "should be QA-checked near dam outlets."
            ),
            "metadata_json": json.dumps({"flowline_count": len(flowlines)}),
        },
    )
    session.commit()
    return len(flowlines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clip HydroRIVERS to reservoir catchments")
    parser.add_argument("--reservoir", choices=sorted(_registry_by_slug()), help="reservoir_id")
    args = parser.parse_args()

    metas = _registry_by_slug()
    selected = [metas[args.reservoir]] if args.reservoir else list(metas.values())

    with Session(make_engine()) as session:
        for meta in selected:
            print(f"[{meta.slug}] HydroRIVERS clip ...", flush=True)
            count = populate_flowlines_for_reservoir(session, meta.slug)
            print(f"  OK {meta.slug}: {count} flowlines", flush=True)


if __name__ == "__main__":
    main()
