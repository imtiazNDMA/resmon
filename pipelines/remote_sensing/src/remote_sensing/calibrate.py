"""Calibration helpers (FR-RS-2). S1 GRD bands are σ⁰ in dB; terrain flattening needs
linear power. These are the dB↔linear conversions used throughout preprocessing.
"""

from __future__ import annotations

import numpy as np


def db_to_linear(db: np.ndarray) -> np.ndarray:
    return np.power(10.0, db / 10.0)


def linear_to_db(linear: np.ndarray) -> np.ndarray:
    return 10.0 * np.log10(np.maximum(linear, 1e-12))


def mask_border_noise(db: np.ndarray, floor_db: float = -30.0) -> np.ndarray:
    """Valid-pixel mask dropping extreme low-dB border/thermal-noise artifacts."""
    return db > floor_db
