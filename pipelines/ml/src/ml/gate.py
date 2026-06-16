"""AC-2 foundational acceptance gate (NFR-ACC-1, FR-GT-7).

Estimation is production-ready only when the rating-curve-derived fill-% agrees with
ground truth within tolerance on a held-out set. D2 resolved: ≤ 10% to start, tighten
toward 5% as extraction improves.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

AC2_TOLERANCE_PCT = 10.0  # D2


@dataclass(frozen=True)
class GateResult:
    passed: bool
    tolerance_pct: float
    per_reservoir_mae: dict[str, float]
    worst_reservoir: str | None
    worst_mae: float


def fill_pct_mae(derived_pct: np.ndarray, bulletin_pct: np.ndarray) -> float:
    return float(np.abs(np.asarray(derived_pct) - np.asarray(bulletin_pct)).mean())


def ac2_gate(
    per_reservoir_mae: dict[str, float], tolerance: float = AC2_TOLERANCE_PCT
) -> GateResult:
    """Pass only if EVERY reservoir's held-out fill-% MAE is within tolerance."""
    if not per_reservoir_mae:
        return GateResult(False, tolerance, {}, None, float("inf"))
    worst = max(per_reservoir_mae, key=lambda r: per_reservoir_mae[r])
    worst_mae = per_reservoir_mae[worst]
    return GateResult(
        passed=worst_mae <= tolerance,
        tolerance_pct=tolerance,
        per_reservoir_mae=per_reservoir_mae,
        worst_reservoir=worst,
        worst_mae=worst_mae,
    )
