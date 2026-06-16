"""Estimation bridge (FR-ML-1): latest SAR area → storage/level/fill via the active
rating curve. This is the inference side of the closed loop (ADR-0005) — in production
there is no bulletin, so this is how a storage number is obtained from a satellite pass.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from ml.curve import RatingCurveFit


def _load_active_curve(conn, reservoir_id: str) -> RatingCurveFit | None:
    row = conn.execute(
        text(
            "SELECT version, area_to_storage_params, area_to_level_params, observed_range, "
            "frl_anchor FROM rating_curve WHERE reservoir_id = :r AND is_active"
        ),
        {"r": reservoir_id},
    ).first()
    if row is None:
        return None
    version, storage_p, level_p, obs_range, anchor = row
    return RatingCurveFit(
        reservoir_id=reservoir_id,
        version=version,
        storage_coeffs=storage_p["coeffs"],
        level_coeffs=level_p["coeffs"],
        observed_range=obs_range,
        capacity_bcm=float(anchor["capacity_bcm"]),
    )


def estimate_current(session: Session) -> dict[str, dict]:
    """For each reservoir with an active curve, map its latest Observation area to
    storage/level/fill. Returns {reservoir_id: {area, storage_bcm, level_m, pct_filled,
    is_extrapolated}}."""
    conn = session.connection()
    out: dict[str, dict] = {}
    reservoirs = conn.execute(text("SELECT reservoir_id FROM reservoir")).scalars().all()
    for rid in reservoirs:
        curve = _load_active_curve(conn, rid)
        if curve is None:
            continue
        obs = conn.execute(
            text(
                "SELECT surface_area FROM observation WHERE reservoir_id = :r "
                "ORDER BY acquisition_date DESC LIMIT 1"
            ),
            {"r": rid},
        ).first()
        if obs is None:
            continue
        area = float(obs[0])
        storage = float(curve.storage_for_area(area))
        out[rid] = {
            "area_km2": area,
            "storage_bcm": storage,
            "level_m": float(curve.level_for_area(area)),
            "pct_filled": storage / curve.capacity_bcm * 100.0,
            "is_extrapolated": curve.is_extrapolated(area),
            "rating_curve_version": curve.version,
        }
    return out


__all__ = ["estimate_current"]
