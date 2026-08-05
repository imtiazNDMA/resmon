"""Load bundled district boundaries into PostGIS for simplified API serving.

Run:
    uv run python scripts/populate_district_boundaries.py
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
from core.db.session import make_engine
from remote_sensing.hydrologic_map import reproject_gdf_to_wgs84, validate_geometries
from shapely.geometry import mapping
from sqlalchemy import text
from sqlalchemy.orm import Session

DISTRICTS_SHP = Path("data/boundaries/districts/District_Boundary.shp")

_DELETE_DISTRICTS = text("DELETE FROM district_boundary")

_INSERT_DISTRICT = text(
    """
    INSERT INTO district_boundary
      (district_id, name, source_dataset, version, geom)
    VALUES
      (:district_id, NULL, 'bundled District_Boundary.shp', 'local',
       ST_Multi(ST_GeomFromGeoJSON(:geom)))
    """
)


def load_district_boundaries(session: Session) -> int:
    if not DISTRICTS_SHP.exists():
        raise FileNotFoundError(f"District shapefile not found: {DISTRICTS_SHP}")

    districts = gpd.read_file(DISTRICTS_SHP)
    districts = reproject_gdf_to_wgs84(districts)
    districts = validate_geometries(districts)

    session.execute(_DELETE_DISTRICTS)
    for district_id, geom in enumerate(districts.geometry, start=1):
        session.execute(
            _INSERT_DISTRICT,
            {
                "district_id": district_id,
                "geom": json.dumps(mapping(geom)),
            },
        )
    session.commit()
    return len(districts)


def main() -> None:
    with Session(make_engine()) as session:
        count = load_district_boundaries(session)
    print(f"OK loaded {count} district boundaries")


if __name__ == "__main__":
    main()
