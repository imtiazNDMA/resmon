"""Fuse Observations ↔ ground truth (FR-DE-3, FR-GT-1) → ``ground_truth_match``.

Each in-band bulletin is paired with its nearest acquisition within ±N days (default 5,
decision D3). The match is a *calibration* artifact (symmetric-nearest is allowed here,
unlike the strictly-backward ABT spine join), recording the actual ``time_gap_days``.
``derived_*`` / residual stay NULL until a rating curve exists (two-pass, §5.6).

Stub observations are excluded: they are generated *from* the bulletins, so matching
them back against ground truth would be circular calibration.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

DEFAULT_TOLERANCE_DAYS = 5  # D3

_FUSE = text(
    """
    INSERT INTO ground_truth_match
      (reservoir_id, gt_date, extraction_version, acquisition_date, time_gap_days,
       scene_ids, extracted_area, area_confidence, extraction_method)
    SELECT
      gt.reservoir_id, gt.date, o.extraction_version, o.acquisition_date,
      abs(o.acquisition_date - gt.date), o.scene_ids, o.surface_area,
      o.area_confidence, o.extraction_method
    FROM ground_truth gt
    JOIN LATERAL (
        SELECT obs.*
        FROM observation obs
        WHERE obs.reservoir_id = gt.reservoir_id
          AND obs.extraction_method <> 'stub'  -- stubs derive FROM bulletins: circular
          AND abs(obs.acquisition_date - gt.date) <= :tol
        ORDER BY abs(obs.acquisition_date - gt.date) ASC, obs.acquisition_date DESC
        LIMIT 1
    ) o ON true
    WHERE gt.row_quality <> 'quarantine'
    ON CONFLICT (reservoir_id, gt_date, extraction_version) DO UPDATE SET
      acquisition_date = EXCLUDED.acquisition_date,
      time_gap_days = EXCLUDED.time_gap_days,
      scene_ids = EXCLUDED.scene_ids,
      extracted_area = EXCLUDED.extracted_area,
      area_confidence = EXCLUDED.area_confidence,
      extraction_method = EXCLUDED.extraction_method
    """
)


def fuse_observations_groundtruth(
    session: Session, tolerance_days: int = DEFAULT_TOLERANCE_DAYS
) -> int:
    """Build/update GroundTruthMatch pairs within tolerance. Returns rows affected."""
    return session.execute(_FUSE, {"tol": tolerance_days}).rowcount  # type: ignore[attr-defined]
