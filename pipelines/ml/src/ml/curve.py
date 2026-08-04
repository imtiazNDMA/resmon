"""Empirical rating curve (FR-GT-4, FR-ML-1) — the estimation bridge (ADR-0005).

Fits per-reservoir Area→Storage(BCM) and Area→Level(m) directly from matched
(extracted_area, bulletin) pairs, so SAR-extraction bias and real basin behaviour are
absorbed. This is the *empirical* half; the DEM hypsometric prior owns above-observed-max
→ FRL (ADR-0004) and is blended in once the DEM shape is available (deferred until GEE).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RatingCurveFit:
    reservoir_id: str
    version: str
    storage_coeffs: list[float]  # np.polyval order: area → storage (BCM)
    level_coeffs: list[float]  # area → level (m)
    observed_range: dict
    capacity_bcm: float

    def storage_for_area(self, area: np.ndarray | float) -> np.ndarray:
        return np.polyval(self.storage_coeffs, area)

    def level_for_area(self, area: np.ndarray | float) -> np.ndarray:
        return np.polyval(self.level_coeffs, area)

    def pct_filled_for_area(self, area: np.ndarray | float) -> np.ndarray:
        return self.storage_for_area(area) / self.capacity_bcm * 100.0

    def is_extrapolated(self, area: float) -> bool:
        return area < self.observed_range["area_min"] or area > self.observed_range["area_max"]


def fit_empirical(
    reservoir_id: str,
    version: str,
    areas: np.ndarray,
    storages: np.ndarray,
    levels: np.ndarray,
    capacity_bcm: float,
    degree: int = 1,
) -> RatingCurveFit:
    """Least-squares Area→Storage and Area→Level. Degree 1 by default (small-data,
    physics-informed; ADR-0006 / §8.5 prefer simple fits)."""
    areas = np.asarray(areas, dtype=float)
    storages = np.asarray(storages, dtype=float)
    levels = np.asarray(levels, dtype=float)
    if capacity_bcm <= 0:
        raise ValueError("capacity_bcm must be positive")
    finite = np.isfinite(areas) & np.isfinite(storages) & np.isfinite(levels)
    areas, storages, levels = areas[finite], storages[finite], levels[finite]
    if areas.size < degree + 1:
        raise ValueError(f"need ≥ {degree + 1} pairs to fit degree-{degree} curve")
    if np.unique(areas).size < degree + 1:
        raise ValueError(f"need ≥ {degree + 1} unique area values to fit degree-{degree} curve")
    storage_coeffs = np.polyfit(areas, storages, degree)
    level_coeffs = np.polyfit(areas, levels, degree)
    observed_range = {
        "area_min": float(areas.min()),
        "area_max": float(areas.max()),
        "storage_min": float(storages.min()),
        "storage_max": float(storages.max()),
    }
    return RatingCurveFit(
        reservoir_id=reservoir_id,
        version=version,
        storage_coeffs=[float(c) for c in storage_coeffs],
        level_coeffs=[float(c) for c in level_coeffs],
        observed_range=observed_range,
        capacity_bcm=capacity_bcm,
    )
