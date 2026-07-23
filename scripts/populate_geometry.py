"""Populate REAL map geometry from live GEE and commit it:
  - reservoir.aoi_geom        ← JRC Global Surface Water max-extent footprint (dam-connected)
  - reservoir.catchment_geom  ← HydroSHEDS HydroBASINS full upstream union
  - a real Sentinel-1 water-extent observation (water_mask_geom + true area), thresholded
    per scene (Otsu on the server-side VH histogram) with honest confidence

Run:  uv run python scripts/populate_geometry.py   (needs geeservice.json)
"""

from __future__ import annotations

import json
import logging
import os

os.environ.setdefault("GEE_SA_KEY_FILE", "geeservice.json")

from core.db.session import make_engine  # noqa: E402
from data_engineering.reservoirs import REGISTRY  # noqa: E402
from remote_sensing.area import area_confidence, polygon_compactness  # noqa: E402
from remote_sensing.extractors import OtsuVH  # noqa: E402
from remote_sensing.gee_real import (  # noqa: E402
    GeeExtractionError,
    delineate_catchment,
    derive_aoi,
    latest_water_extent,
)
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("populate_geometry")

# Published drainage areas for the catchment sanity check (B4); Bhakra/Gobind Sagar from
# BBMB. Extend as figures are sourced for the other dams.
EXPECTED_CATCHMENT_KM2: dict[str, float] = {"gobind_sagar": 56_900.0}

_UPD_RESERVOIR = text(
    """
    UPDATE reservoir SET
      aoi_geom = ST_Multi(ST_GeomFromGeoJSON(:aoi)), aoi_version = 'jrc_gsw_v1',
      catchment_geom = ST_Multi(ST_GeomFromGeoJSON(:cat)), catchment_version = 'hybas7_v1',
      updated_at = now()
    WHERE reservoir_id = :r
    """
)

_SEL_ORBIT = text("SELECT orbit_relative, pass_direction FROM reservoir WHERE reservoir_id = :r")

# observation.layover_shadow_fraction is NOT NULL (core/src/core/models/observation.py),
# and no DEM layover/shadow mask exists yet (deferred: needs GEE terrain execution).
# 0 is recorded as a *placeholder lower bound*, NOT a measurement — revisit when the
# terrain pipeline lands.
_UPSERT_OBS = text(
    """
    INSERT INTO observation
      (reservoir_id, acquisition_date, surface_area, area_confidence, water_mask_ref,
       extraction_method, extraction_version, scene_ids, orbit_relative, pass_direction,
       aoi_version, layover_shadow_fraction, processing_params, water_mask_geom)
    VALUES
      (:r, :d, :area, :conf, 'gee://s1', :method, :version, ARRAY[:scene], :orbit,
       :pass, 'jrc_gsw_v1', 0, CAST(:pp AS jsonb), ST_Multi(ST_GeomFromGeoJSON(:wgeo)))
    ON CONFLICT (reservoir_id, acquisition_date) DO UPDATE SET
      surface_area = EXCLUDED.surface_area,
      area_confidence = EXCLUDED.area_confidence,
      water_mask_geom = EXCLUDED.water_mask_geom,
      extraction_method = EXCLUDED.extraction_method,
      extraction_version = EXCLUDED.extraction_version,
      processing_params = EXCLUDED.processing_params
    """
)


def main() -> None:
    with Session(make_engine()) as s:
        for m in REGISTRY.values():
            print(f"[{m.slug}] JRC-GSW max-extent AOI ...", flush=True)
            aoi = derive_aoi(m.dam_lon, m.dam_lat)
            print(f"[{m.slug}] HydroBASINS upstream catchment ...", flush=True)
            cat = delineate_catchment(
                m.dam_lon, m.dam_lat, expected_km2=EXPECTED_CATCHMENT_KM2.get(m.slug)
            )
            s.execute(_UPD_RESERVOIR, {"r": m.slug, "aoi": json.dumps(aoi), "cat": json.dumps(cat)})
            s.commit()  # AOI/catchment are useful even if the S1 extraction below skips

            # Frozen acquisition geometry comes from the reservoir config row (FR-RS-1).
            row = s.execute(_SEL_ORBIT, {"r": m.slug}).one_or_none()
            orbit, pass_dir = row if row else (m.orbit_relative, m.pass_direction)

            print(f"[{m.slug}] latest Sentinel-1 water extent ...", flush=True)
            try:
                w = latest_water_extent(
                    aoi, reservoir_id=m.slug, orbit_relative=orbit, pass_direction=pass_dir
                )
            except GeeExtractionError as exc:
                log.warning("[%s] skipping observation write: %s", m.slug, exc)
                continue
            if w is None:  # extractor abstained (no credible water/land bimodality)
                log.warning(
                    "[%s] extractor abstained on the latest scene; not writing an observation",
                    m.slug,
                )
                continue

            # Honest confidence (FR-RS-3): unified separability from the adaptive
            # threshold + mask compactness; layover term is the 0 placeholder above.
            conf = area_confidence(w["separability"], polygon_compactness(w["geojson"]), 0.0)
            s.execute(
                _UPSERT_OBS,
                {
                    "r": m.slug,
                    "d": w["acquisition_date"],
                    "area": w["area_km2"],
                    "conf": conf,
                    "method": OtsuVH.name,  # registered extractor name (ADR-0007)
                    "version": OtsuVH.version,
                    "scene": w["scene_id"],
                    "orbit": w["orbit_relative"],
                    "pass": w["pass_direction"],
                    "pp": json.dumps(w["processing"]),
                    "wgeo": json.dumps(w["geojson"]),
                },
            )
            s.commit()
            print(
                f"  OK {m.slug}: water {w['area_km2']:.1f} km2 on {w['acquisition_date']} "
                f"(scene {w['scene_id'][:24]}..., threshold {w['threshold_db']:.1f} dB, "
                f"confidence {conf:.2f})",
                flush=True,
            )
    print("Geometry populate complete.")


if __name__ == "__main__":
    main()
