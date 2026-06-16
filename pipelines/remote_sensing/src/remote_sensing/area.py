"""True surface area + confidence (FR-RS-3).

Area is a true-area measure (pixel count × per-pixel ground area), never raw lat/long
pixel counts. Confidence combines cluster separability, mask compactness, and the
layover/shadow fraction — monotone in each (ADR-0007 robustness).
"""

from __future__ import annotations

import numpy as np

S1_PIXEL_AREA_M2 = 100.0  # 10 m × 10 m; in GEE this is ee.Image.pixelArea()


def surface_area_km2(mask: np.ndarray, pixel_area_m2: float = S1_PIXEL_AREA_M2) -> float:
    """True water area in km² from a binary mask and the per-pixel ground area."""
    return float(mask.sum()) * pixel_area_m2 / 1e6


def compactness(mask: np.ndarray) -> float:
    """Isoperimetric-style compactness in (0, 1]; a fragmented/noisy mask scores low."""
    area = float(mask.sum())
    if area <= 0:
        return 0.0
    # 4-connected boundary length: edges where a water pixel borders non-water.
    m = mask.astype(bool)
    perim = 0.0
    perim += np.sum(m[:, :-1] != m[:, 1:])
    perim += np.sum(m[:-1, :] != m[1:, :])
    perim += np.sum(m[:, 0]) + np.sum(m[:, -1]) + np.sum(m[0, :]) + np.sum(m[-1, :])
    if perim <= 0:
        return 1.0
    return float(min(1.0, 4.0 * np.pi * area / (perim**2)))


def area_confidence(
    separability: float, compactness_score: float, layover_shadow_fraction: float
) -> float:
    """Combine sub-scores into area_confidence ∈ [0, 1]. Weighted product so any single
    collapsing signal (e.g. wind-roughened water → low separability) caps confidence."""
    sep = min(max(separability, 0.0), 1.0)
    comp = min(max(compactness_score, 0.0), 1.0)
    layover_ok = 1.0 - min(max(layover_shadow_fraction, 0.0), 1.0)
    return float(sep**0.5 * comp**0.25 * layover_ok**0.25)
