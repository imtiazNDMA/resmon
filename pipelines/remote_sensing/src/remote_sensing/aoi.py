"""AOI bootstrap from JRC Global Surface Water (FR-RS-1, D8).

Reproducible derivation: threshold the JRC GSW occurrence (or take the ``max_extent``
band), select the **water component connected to the dam** (pure-numpy flood fill, not
an all-pixels bbox), buffer, and emit a versioned polygon. The occurrence floor is
deliberately low (≥5 %): the rarely-inundated near-FRL flood margin is exactly the zone
an early-warning AOI must include, and thresholds like ≥50 % exclude it. In production
the occurrence raster comes from GEE (``JRC/GSW1_4/GlobalSurfaceWater``) via the
backend; here the logic runs on any occurrence array. Each AOI is eyeballed once before
freezing. ``gee_real.derive_aoi`` is the server-side twin and shares these constants so
the two code paths cannot drift apart.
"""

from __future__ import annotations

from collections import deque

import numpy as np

GSW_ASSET = "JRC/GSW1_4/GlobalSurfaceWater"
#: GSW band that is 1 wherever water was EVER observed (1984–2021) — the historical
#: maximum extent, i.e. the correct sizing for a never-clipped AOI (FR-RS-1).
GSW_MAX_EXTENT_BAND = "max_extent"
#: Occurrence floor (%) shared by the array path and ``gee_real``. Low on purpose:
#: ≥50 % would exclude the near-FRL flood margin that matters most.
GSW_OCCURRENCE_MIN_PCT = 5.0


def dam_connected_component(water: np.ndarray, seed: tuple[int, int]) -> np.ndarray:
    """4-connected flood fill from ``seed``: the water component containing the dam.

    Pure numpy/BFS — keeps AOI derivation credential-free and unit-testable.
    """
    water = np.asarray(water, dtype=bool)
    r0, c0 = seed
    if not water[r0, c0]:
        raise ValueError(f"seed pixel {seed} is not water")
    comp = np.zeros_like(water)
    comp[r0, c0] = True
    queue: deque[tuple[int, int]] = deque([(r0, c0)])
    nrows, ncols = water.shape
    while queue:
        r, c = queue.popleft()
        for rr, cc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= rr < nrows and 0 <= cc < ncols and water[rr, cc] and not comp[rr, cc]:
                comp[rr, cc] = True
                queue.append((rr, cc))
    return comp


def _snap_to_water(
    water: np.ndarray, row: int, col: int, *, max_snap_px: int = 10
) -> tuple[int, int]:
    """Nearest water pixel to (row, col) — the dam point sits on the dam wall, so it is
    usually adjacent to (not on) a water pixel."""
    if water[row, col]:
        return row, col
    rows, cols = np.nonzero(water)
    d2 = (rows - row) ** 2 + (cols - col) ** 2
    i = int(d2.argmin())
    if d2[i] > max_snap_px**2:
        raise ValueError(
            f"no water pixel within {max_snap_px} px of the dam point; check dam coordinates"
        )
    return int(rows[i]), int(cols[i])


def aoi_bbox_from_occurrence(
    occurrence: np.ndarray,
    lons: np.ndarray,
    lats: np.ndarray,
    *,
    dam_lon: float | None = None,
    dam_lat: float | None = None,
    threshold_pct: float = GSW_OCCURRENCE_MIN_PCT,
    buffer_deg: float = 0.01,
) -> dict:
    """Return an AOI as a GeoJSON-like Polygon dict: the buffered bounding box of the
    **dam-connected** water component (when dam coordinates are given), else of all
    pixels whose water-occurrence ≥ ``threshold_pct``. Sized to historical max water
    extent so high-water (FRL) states are never clipped (FR-RS-1)."""
    occurrence = np.asarray(occurrence, dtype=float)
    water = np.where(np.isfinite(occurrence), occurrence, -np.inf) >= threshold_pct
    if not water.any():
        raise ValueError("no pixels exceed the occurrence threshold; check inputs")
    selection = "all_pixels"
    if dam_lon is not None and dam_lat is not None:
        row = int(np.abs(np.asarray(lats, dtype=float) - dam_lat).argmin())
        col = int(np.abs(np.asarray(lons, dtype=float) - dam_lon).argmin())
        seed = _snap_to_water(water, row, col)
        water = dam_connected_component(water, seed)
        selection = "dam_connected_component"
    rows, cols = np.where(water)
    lat_min, lat_max = lats[rows].min() - buffer_deg, lats[rows].max() + buffer_deg
    lon_min, lon_max = lons[cols].min() - buffer_deg, lons[cols].max() + buffer_deg
    ring = [
        [lon_min, lat_min],
        [lon_max, lat_min],
        [lon_max, lat_max],
        [lon_min, lat_max],
        [lon_min, lat_min],
    ]
    return {
        "type": "Polygon",
        "coordinates": [ring],
        "properties": {
            "source": GSW_ASSET,
            "occurrence_threshold_pct": threshold_pct,
            "buffer_deg": buffer_deg,
            "selection": selection,
        },
    }


def polygon_to_wkt(aoi: dict) -> str:
    """GeoJSON Polygon dict → WKT (for ST_GeomFromText persistence)."""
    ring = aoi["coordinates"][0]
    coords = ", ".join(f"{x} {y}" for x, y in ring)
    return f"MULTIPOLYGON((({coords})))"
