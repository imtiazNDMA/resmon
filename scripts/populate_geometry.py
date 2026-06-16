"""Populate REAL map geometry from live GEE and commit it:
  - reservoir.aoi_geom        ← JRC Global Surface Water footprint
  - reservoir.catchment_geom  ← HydroSHEDS HydroBASINS unit
  - a real Sentinel-1 water-extent observation (water_mask_geom + true area)

Run:  uv run python scripts/populate_geometry.py   (needs geeservice.json)
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("GEE_SA_KEY_FILE", "geeservice.json")

from core.db.session import make_engine  # noqa: E402
from data_engineering.reservoirs import REGISTRY  # noqa: E402
from remote_sensing.gee_real import (  # noqa: E402
    delineate_catchment,
    derive_aoi,
    latest_water_extent,
)
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

_UPD_RESERVOIR = text(
    """
    UPDATE reservoir SET
      aoi_geom = ST_Multi(ST_GeomFromGeoJSON(:aoi)), aoi_version = 'jrc_gsw_v1',
      catchment_geom = ST_Multi(ST_GeomFromGeoJSON(:cat)), catchment_version = 'hybas7_v1',
      updated_at = now()
    WHERE reservoir_id = :r
    """
)

_UPSERT_OBS = text(
    """
    INSERT INTO observation
      (reservoir_id, acquisition_date, surface_area, area_confidence, water_mask_ref,
       extraction_method, extraction_version, scene_ids, orbit_relative, pass_direction,
       aoi_version, layover_shadow_fraction, processing_params, water_mask_geom)
    VALUES
      (:r, :d, :area, 0.8, 'gee://s1', 's1_vh_threshold', 'gee_v1', ARRAY[:scene], :orbit,
       :pass, 'jrc_gsw_v1', 0, CAST(:pp AS jsonb), ST_Multi(ST_GeomFromGeoJSON(:wgeo)))
    ON CONFLICT (reservoir_id, acquisition_date) DO UPDATE SET
      surface_area = EXCLUDED.surface_area, water_mask_geom = EXCLUDED.water_mask_geom,
      extraction_method = EXCLUDED.extraction_method
    """
)


def main() -> None:
    with Session(make_engine()) as s:
        for m in REGISTRY.values():
            print(f"[{m.slug}] JRC-GSW AOI ...", flush=True)
            aoi = derive_aoi(m.dam_lon, m.dam_lat)
            print(f"[{m.slug}] HydroBASINS catchment ...", flush=True)
            cat = delineate_catchment(m.dam_lon, m.dam_lat)
            s.execute(_UPD_RESERVOIR, {"r": m.slug, "aoi": json.dumps(aoi), "cat": json.dumps(cat)})

            print(f"[{m.slug}] latest Sentinel-1 water extent ...", flush=True)
            w = latest_water_extent(aoi)
            s.execute(
                _UPSERT_OBS,
                {
                    "r": m.slug,
                    "d": w["acquisition_date"],
                    "area": w["area_km2"],
                    "scene": w["scene_id"],
                    "orbit": w["orbit_relative"],
                    "pass": w["pass_direction"],
                    "pp": json.dumps({"vh_threshold": -18, "source": "gee_s1_vh"}),
                    "wgeo": json.dumps(w["geojson"]),
                },
            )
            s.commit()
            print(
                f"  OK {m.slug}: water {w['area_km2']:.1f} km2 on {w['acquisition_date']} "
                f"(scene {w['scene_id'][:24]}...)",
                flush=True,
            )
    print("Geometry populate complete.")


if __name__ == "__main__":
    main()
