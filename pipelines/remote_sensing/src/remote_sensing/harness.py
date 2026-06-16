"""Extraction-method selection harness (ADR-0007). Each candidate extractor produces
areas on bulletin-matched scenes; we co-fit a simple area→fill curve, score fill-% MAE
**broken out by regime** (monsoon / winter-ice / wind), and select the *robust* candidate
— the one whose worst-regime error is lowest, not the lowest-mean. The full version
co-fits the blended rating curve and registers the winner in MLflow (Phase 4/T-16).
"""

from __future__ import annotations

import numpy as np


def fit_area_to_pct(areas: np.ndarray, pcts: np.ndarray) -> tuple[float, float]:
    """Least-squares linear area→fill% (a stand-in for the blended curve during selection)."""
    a = np.asarray(areas, dtype=float)
    p = np.asarray(pcts, dtype=float)
    design = np.column_stack([a, np.ones_like(a)])
    slope, intercept = np.linalg.lstsq(design, p, rcond=None)[0]
    return float(slope), float(intercept)


def regime_mae(areas: np.ndarray, pcts: np.ndarray, regimes: list[str]) -> dict[str, float]:
    """Fit one curve on all pairs, then fill-% MAE per regime."""
    slope, intercept = fit_area_to_pct(areas, pcts)
    pred = slope * np.asarray(areas, dtype=float) + intercept
    err = np.abs(pred - np.asarray(pcts, dtype=float))
    out: dict[str, float] = {}
    regimes_arr = np.asarray(regimes)
    for reg in sorted(set(regimes)):
        out[reg] = float(err[regimes_arr == reg].mean())
    return out


def select_robust(candidate_regime_mae: dict[str, dict[str, float]]) -> tuple[str, float]:
    """Pick the candidate with the lowest **worst-regime** MAE (robust selection). Returns
    ``(winner_name, worst_regime_mae)``. A method that collapses in any regime loses."""
    if not candidate_regime_mae:
        raise ValueError("no candidates to select from")
    worst = {name: max(maes.values()) for name, maes in candidate_regime_mae.items()}
    winner = min(worst, key=lambda n: worst[n])
    return winner, worst[winner]
