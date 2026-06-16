"""Forecast baselines the model must beat (NFR-ACC-2, AC-4).

- **persistence**: tomorrow looks like today → Δfill = 0.
- **climatology**: tomorrow looks like the seasonal normal → Δfill = normal(target) − fill(now).
  The Normal-Storage proxy (ADR-0002) is our climatology.
"""

from __future__ import annotations

import numpy as np


def persistence_delta(n: int) -> np.ndarray:
    """Predicted Δfill under persistence: zero (no change)."""
    return np.zeros(n)


def climatology_delta(current_pct: np.ndarray, normal_pct_target: np.ndarray) -> np.ndarray:
    """Predicted Δfill under climatology: move toward the seasonal normal at the target date."""
    return np.asarray(normal_pct_target, dtype=float) - np.asarray(current_pct, dtype=float)


def mae(pred_delta: np.ndarray, actual_delta: np.ndarray) -> float:
    return float(np.abs(np.asarray(pred_delta) - np.asarray(actual_delta)).mean())
