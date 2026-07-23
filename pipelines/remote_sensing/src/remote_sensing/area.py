"""True surface area + confidence (FR-RS-3).

Area is a true-area measure (pixel count × per-pixel ground area), never raw lat/long
pixel counts. Confidence combines cluster separability, mask compactness, and the
layover/shadow fraction — monotone in each (ADR-0007 robustness).
"""

from __future__ import annotations

import math

import numpy as np

_EARTH_R_M = 6_371_000.0


def surface_area_km2(mask: np.ndarray, pixel_area_m2: float) -> float:
    """True water area in km² from a binary mask and an explicit per-pixel ground area."""
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


def _outer_rings(geom: dict) -> list[list[list[float]]]:
    """Outer rings of a GeoJSON Polygon / MultiPolygon / GeometryCollection."""
    gtype = geom.get("type")
    if gtype == "Polygon":
        coords = geom.get("coordinates") or []
        return [coords[0]] if coords else []
    if gtype == "MultiPolygon":
        return [poly[0] for poly in (geom.get("coordinates") or []) if poly]
    if gtype == "GeometryCollection":
        rings: list[list[list[float]]] = []
        for g in geom.get("geometries") or []:
            rings.extend(_outer_rings(g))
        return rings
    return []


def _ring_area_perimeter_m(ring: list[list[float]], lat0: float) -> tuple[float, float]:
    """Planar shoelace area (m²) and perimeter (m) of a lon/lat ring via a local
    equirectangular projection — accurate enough for a compactness *score*."""
    kx = _EARTH_R_M * math.cos(math.radians(lat0)) * math.pi / 180.0
    ky = _EARTH_R_M * math.pi / 180.0
    xs = np.array([p[0] for p in ring], dtype=float) * kx
    ys = np.array([p[1] for p in ring], dtype=float) * ky
    if xs.size < 3:
        return 0.0, 0.0
    area = 0.5 * abs(float(np.dot(xs, np.roll(ys, -1)) - np.dot(ys, np.roll(xs, -1))))
    perim = float(np.hypot(np.diff(xs, append=xs[0]), np.diff(ys, append=ys[0])).sum())
    return area, perim


def polygon_compactness(geojson: dict) -> float:
    """Isoperimetric compactness in [0, 1] of a vectorised GeoJSON water mask — the
    vector analogue of :func:`compactness` for the live-GEE path, so its
    ``area_confidence`` is honest instead of hardcoded."""
    rings = _outer_rings(geojson)
    if not rings:
        return 0.0
    total_area = 0.0
    total_perim = 0.0
    for ring in rings:
        lat0 = float(np.mean([p[1] for p in ring])) if ring else 0.0
        a, p = _ring_area_perimeter_m(ring, lat0)
        total_area += a
        total_perim += p
    if total_area <= 0 or total_perim <= 0:
        return 0.0
    return float(min(1.0, 4.0 * np.pi * total_area / (total_perim**2)))


def area_confidence(
    separability: float, compactness_score: float, layover_shadow_fraction: float
) -> float:
    """Combine sub-scores into area_confidence ∈ [0, 1]. Weighted product so any single
    collapsing signal (e.g. wind-roughened water → low separability) caps confidence."""
    sep = min(max(separability, 0.0), 1.0)
    comp = min(max(compactness_score, 0.0), 1.0)
    layover_ok = 1.0 - min(max(layover_shadow_fraction, 0.0), 1.0)
    return float(sep**0.5 * comp**0.25 * layover_ok**0.25)
