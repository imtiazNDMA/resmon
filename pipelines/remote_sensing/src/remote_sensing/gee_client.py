"""Thin GEE client over the platform ``DataAccessBackend`` (FR-RS-1, §4.4).

Never calls ``ee.Initialize()`` directly — all access goes through the swappable backend
so an openEO / Planetary Computer / SNAP backend can replace GEE without touching the
extraction code.
"""

from __future__ import annotations

from datetime import date

from pipelines_common.dataaccess import DataAccessBackend, get_backend

S1_GRD = "COPERNICUS/S1_GRD"
DEM_GLO30 = "COPERNICUS/DEM/GLO30"


class GeeClient:
    def __init__(self, backend: DataAccessBackend | None = None) -> None:
        self.backend = backend or get_backend()

    def list_scenes(self, aoi: dict, start: date, end: date) -> list[dict]:
        """In-orbit scene metadata for nearest-match + freshness (FR-RS-1)."""
        return self.backend.list_scenes(S1_GRD, aoi, start, end)

    def get_s1(self, aoi: dict, start: date, end: date, orbit: int, pass_dir: str):
        """Sentinel-1 GRD over the AOI at fixed orbit/pass (FR-RS-1)."""
        return self.backend.get_s1_grd(aoi, start, end, orbit, pass_dir)

    def get_dem(self, aoi: dict):
        """DEM for terrain flattening, layover/shadow geometry, hypsometry (FR-RS-2/4)."""
        return self.backend.get_dem(aoi, DEM_GLO30)
