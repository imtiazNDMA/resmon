"""Seed the 3 pilot reservoirs (plan 02 §7). Idempotent upsert. Geometry is a
placeholder buffer around the dam point until RS derives the real AOI from JRC GSW
(Phase 3, FR-RS-1). Release thresholds default from FRL fill bands (D7).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from data_engineering.reservoirs import REGISTRY

_UPSERT = text(
    """
    INSERT INTO reservoir
      (reservoir_id, name, basin, dam_point, frl_m, live_capacity_bcm,
       aoi_geom, aoi_version, orbit_relative, pass_direction, release_thresholds)
    VALUES (
       :slug, :name, :basin,
       ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
       :frl, :cap,
       ST_Multi(ST_Buffer(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 0.05)),
       'placeholder_v0', :orbit, :pass_dir,
       CAST(:thresholds AS jsonb)
    )
    ON CONFLICT (reservoir_id) DO UPDATE SET
       name = EXCLUDED.name, basin = EXCLUDED.basin, dam_point = EXCLUDED.dam_point,
       frl_m = EXCLUDED.frl_m, live_capacity_bcm = EXCLUDED.live_capacity_bcm,
       orbit_relative = EXCLUDED.orbit_relative, pass_direction = EXCLUDED.pass_direction,
       release_thresholds = EXCLUDED.release_thresholds, updated_at = now(),
       -- aoi_geom/aoi_version are only refreshed while still the placeholder: the real
       -- AOI (jrc_gsw_v1, scripts/populate_geometry.py) must never be clobbered by a
       -- seed rerun.
       aoi_geom = CASE WHEN reservoir.aoi_version = 'placeholder_v0'
                       THEN EXCLUDED.aoi_geom ELSE reservoir.aoi_geom END,
       aoi_version = CASE WHEN reservoir.aoi_version = 'placeholder_v0'
                          THEN EXCLUDED.aoi_version ELSE reservoir.aoi_version END
    """
)


def seed_reservoirs(session: Session) -> int:
    """Insert/update the pilot fleet. Returns the number of reservoirs seeded."""
    for m in REGISTRY.values():
        thresholds = '{"watch": {"pct": 90}, "warning": {"pct": 95}, "imminent": {"pct": 98}}'
        session.execute(
            _UPSERT,
            {
                "slug": m.slug,
                "name": m.name,
                "basin": m.basin,
                "lon": m.dam_lon,
                "lat": m.dam_lat,
                "frl": m.frl_m,
                "cap": m.live_capacity_bcm,
                "orbit": m.orbit_relative,
                "pass_dir": m.pass_direction,
                "thresholds": thresholds,
            },
        )
    return len(REGISTRY)
