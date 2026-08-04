"""Static administrative boundary GeoJSON sources."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import shapefile

ROOT = Path(__file__).resolve().parents[3]
DISTRICTS_SHP = ROOT / "data" / "boundaries" / "districts" / "District_Boundary.shp"


@lru_cache(maxsize=1)
def district_boundaries() -> dict[str, Any]:
    """District boundaries from the bundled WGS84 shapefile.

    The source directory does not include a DBF attribute table, so features carry a
    stable ordinal id and geometry bounds only.
    """
    if not DISTRICTS_SHP.exists():
        return {"type": "FeatureCollection", "features": []}
    reader = shapefile.Reader(shp=str(DISTRICTS_SHP))
    features = []
    for idx, shape in enumerate(reader.shapes(), start=1):
        if shape.shapeType == shapefile.NULL:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": shape.__geo_interface__,
                "properties": {
                    "district_id": idx,
                    "bbox": [float(x) for x in shape.bbox],
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}
