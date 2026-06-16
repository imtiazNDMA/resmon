"""RS pipeline (framework): scenes → extract → area/confidence → real ``Observation`` rows.

In production each step runs against GEE through ``GeeClient`` (Sentinel-1 γ⁰, terrain
flattening, layover masking). Here, with no GEE, it synthesizes a backscatter scene per
bulletin date (a low-VH water blob sized by fill) so the *real* extractor + area +
confidence path runs end to end and emits non-stub Observations that replace the stubs
(Phase 3 exit). ``derived_volume/level`` stay NULL until the rating curve exists (§4).
"""

from __future__ import annotations

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from remote_sensing.area import area_confidence, compactness, surface_area_km2
from remote_sensing.extractors import get_extractor

# Synthetic-scene constants (test/framework only).
_GRID = 64
_SYNTH_PIXEL_AREA_M2 = 100e6 / (_GRID * _GRID)  # full grid ≈ 100 km²
_VH_WATER_DB, _VH_LAND_DB = -22.0, -10.0
_VV_WATER_DB, _VV_LAND_DB = -17.0, -7.0

_OBS_UPSERT = text(
    """
    INSERT INTO observation
      (reservoir_id, acquisition_date, surface_area, area_confidence, water_mask_ref,
       extraction_method, extraction_version, scene_ids, orbit_relative, pass_direction,
       aoi_version, layover_shadow_fraction, processing_params)
    VALUES
      (:reservoir_id, :acquisition_date, :surface_area, :area_confidence, :water_mask_ref,
       :extraction_method, :extraction_version, ARRAY['synthetic'], :orbit_relative,
       :pass_direction, :aoi_version, :layover_shadow_fraction, CAST(:processing_params AS jsonb))
    ON CONFLICT (reservoir_id, acquisition_date) DO UPDATE SET
      surface_area = EXCLUDED.surface_area,
      area_confidence = EXCLUDED.area_confidence,
      extraction_method = EXCLUDED.extraction_method,
      extraction_version = EXCLUDED.extraction_version,
      water_mask_ref = EXCLUDED.water_mask_ref
    """
)


def synth_scene(pct_filled: float, *, seed: int = 0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A deterministic VV/VH (dB) scene with a water block covering ``pct_filled`` % of the
    grid. Returns (vv, vh, valid_mask)."""
    rng = np.random.default_rng(seed)
    frac = min(max(pct_filled / 100.0, 0.0), 1.0)
    n_water = int(round(frac * _GRID * _GRID))
    flat_idx = np.arange(_GRID * _GRID)
    water_flat = np.zeros(_GRID * _GRID, dtype=bool)
    water_flat[flat_idx[:n_water]] = True
    water = water_flat.reshape(_GRID, _GRID)
    vh = np.where(water, _VH_WATER_DB, _VH_LAND_DB) + rng.normal(0, 1.0, (_GRID, _GRID))
    vv = np.where(water, _VV_WATER_DB, _VV_LAND_DB) + rng.normal(0, 1.0, (_GRID, _GRID))
    valid = np.ones((_GRID, _GRID), dtype=bool)
    return vv, vh, valid


def run_rs_pipeline(session: Session, extractor_name: str = "otsu_vh") -> dict:
    """Extract water + emit real Observations for every in-band bulletin date. Returns a
    summary (observations written, mean confidence)."""
    extractor = get_extractor(extractor_name)
    conn = session.connection()
    reservoirs = conn.execute(
        text("SELECT reservoir_id, orbit_relative, pass_direction, aoi_version FROM reservoir")
    ).all()

    rows: list[dict] = []
    confidences: list[float] = []
    for rid, orbit, pass_dir, aoi_version in reservoirs:
        gt = conn.execute(
            text(
                "SELECT date, pct_filled FROM ground_truth "
                "WHERE reservoir_id = :r AND row_quality <> 'quarantine' AND pct_filled IS NOT NULL"
            ),
            {"r": rid},
        ).all()
        for i, (gdate, pct) in enumerate(gt):
            vv, vh, valid = synth_scene(float(pct), seed=i)
            res = extractor.extract(vv, vh, valid, context={"reservoir_id": rid})
            area = surface_area_km2(res.water_mask, _SYNTH_PIXEL_AREA_M2)
            conf = area_confidence(res.separability, compactness(res.water_mask), 0.0)
            confidences.append(conf)
            rows.append(
                {
                    "reservoir_id": rid,
                    "acquisition_date": gdate,
                    "surface_area": area,
                    "area_confidence": conf,
                    "water_mask_ref": f"synthetic://{rid}/{gdate}",
                    "extraction_method": extractor.name,
                    "extraction_version": extractor.version,
                    "orbit_relative": orbit,
                    "pass_direction": pass_dir,
                    "aoi_version": aoi_version,
                    "layover_shadow_fraction": 0.0,
                    "processing_params": f'{{"separability": {res.separability:.3f}}}',
                }
            )
    if rows:
        session.execute(_OBS_UPSERT, rows)
    mean_conf = float(np.mean(confidences)) if confidences else 0.0
    return {
        "observations_written": len(rows),
        "extraction_method": extractor.name,
        "mean_confidence": mean_conf,
    }
