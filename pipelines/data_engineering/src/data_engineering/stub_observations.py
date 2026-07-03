"""Generate stub ``Observation`` rows (contract stub rule, ADR-0003) so DE/ML can build
the ABT before real SAR lands (Phase 3). Each bulletin date gets a synthetic surface
area from a rough monotonic inversion of fill (area ∝ fill^0.7); ``extraction_method =
'stub'`` makes them trivially filterable and replaceable.

Two guards keep stubs from ever displacing real SAR data:

* reservoirs that already have any non-stub observation are skipped entirely (the stub
  scaffolding has served its purpose there), and
* the ``DO UPDATE`` only fires on rows that are still stubs — a rerun can never
  overwrite a real observation's payload.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

_STUB_INSERT = text(
    """
    INSERT INTO observation
      (reservoir_id, acquisition_date, surface_area, area_confidence, water_mask_ref,
       extraction_method, extraction_version, scene_ids, orbit_relative, pass_direction,
       aoi_version, layover_shadow_fraction, processing_params)
    SELECT
      gt.reservoir_id,
      gt.date,
      100.0 * power(GREATEST(COALESCE(gt.pct_filled, 0), 0) / 100.0, 0.7),
      0.5,
      'stub://',
      'stub',
      'stub_v0',
      ARRAY['stub'],
      r.orbit_relative,
      r.pass_direction,
      'placeholder_v0',
      0,
      '{}'::jsonb
    FROM ground_truth gt
    JOIN reservoir r ON r.reservoir_id = gt.reservoir_id
    WHERE gt.row_quality <> 'quarantine' AND gt.pct_filled IS NOT NULL
      -- Skip reservoirs where real (non-stub) SAR observations already exist: the stub
      -- scaffolding is only for bootstrapping before real extractions land.
      AND NOT EXISTS (
        SELECT 1 FROM observation real_obs
        WHERE real_obs.reservoir_id = gt.reservoir_id
          AND real_obs.extraction_method <> 'stub'
      )
    ON CONFLICT (reservoir_id, acquisition_date) DO UPDATE SET
      surface_area = EXCLUDED.surface_area,
      area_confidence = EXCLUDED.area_confidence,
      water_mask_ref = EXCLUDED.water_mask_ref,
      extraction_method = EXCLUDED.extraction_method,
      extraction_version = EXCLUDED.extraction_version,
      scene_ids = EXCLUDED.scene_ids,
      orbit_relative = EXCLUDED.orbit_relative,
      pass_direction = EXCLUDED.pass_direction,
      aoi_version = EXCLUDED.aoi_version,
      layover_shadow_fraction = EXCLUDED.layover_shadow_fraction,
      processing_params = EXCLUDED.processing_params
    -- Never clobber a real SAR observation with a stub on rerun.
    WHERE observation.extraction_method = 'stub'
    """
)


def generate_stub_observations(session: Session) -> int:
    """Upsert one stub Observation per in-band bulletin date. Returns rows affected."""
    return session.execute(_STUB_INSERT).rowcount  # type: ignore[attr-defined]
