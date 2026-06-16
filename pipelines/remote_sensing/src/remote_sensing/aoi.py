"""AOI bootstrap from JRC Global Surface Water (FR-RS-1, D8).

Reproducible derivation: threshold the JRC GSW max-water occurrence, take the extent of
the water component near the dam, buffer, and emit a versioned polygon. In production the
occurrence raster comes from GEE (`JRC/GSW1_4/GlobalSurfaceWater`) via the backend; here
the logic runs on any occurrence array. Each AOI is eyeballed once before freezing.
"""

from __future__ import annotations

import numpy as np

GSW_ASSET = "JRC/GSW1_4/GlobalSurfaceWater"


def aoi_bbox_from_occurrence(
    occurrence: np.ndarray,
    lons: np.ndarray,
    lats: np.ndarray,
    *,
    threshold_pct: float = 50.0,
    buffer_deg: float = 0.01,
) -> dict:
    """Return an AOI as a GeoJSON-like Polygon dict: the buffered bounding box of pixels
    whose water-occurrence ≥ ``threshold_pct``. Sized to historical max water extent so
    high-water (FRL) states are never clipped (FR-RS-1)."""
    water = occurrence >= threshold_pct
    if not water.any():
        raise ValueError("no pixels exceed the occurrence threshold; check inputs")
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
        },
    }


def polygon_to_wkt(aoi: dict) -> str:
    """GeoJSON Polygon dict → WKT (for ST_GeomFromText persistence)."""
    ring = aoi["coordinates"][0]
    coords = ", ".join(f"{x} {y}" for x, y in ring)
    return f"MULTIPOLYGON((({coords})))"
