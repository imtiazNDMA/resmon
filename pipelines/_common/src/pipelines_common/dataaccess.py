"""The swappable satellite/geodata access boundary (§4.4, ADR-0005 closed loop).

All three pipelines import only :class:`DataAccessBackend`; the concrete backend is
chosen by the ``DATA_ACCESS_BACKEND`` env var via :func:`get_backend`. The v1 default
is ``GEEBackend`` (geemap/xee, non-commercial tier). ``FixtureBackend`` returns canned
data so CI and tests run without GEE credentials. A future openEO / Planetary Computer
backend slots in here without touching any caller.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # keep xarray import cost off the hot path / optional backends
    import xarray as xr

# Default GEE asset IDs (mirrors requirements.md §6.6).
DEM_GLO30 = "COPERNICUS/DEM/GLO30"
S1_GRD = "COPERNICUS/S1_GRD"


class DataAccessBackend(ABC):
    """Thin, swappable satellite/geodata access boundary.

    v1 impl: GEE (geemap/xee). Designed so an openEO / Planetary Computer backend can
    replace it without changing any pipeline caller (§4.4).
    """

    name: str

    @abstractmethod
    def get_s1_grd(
        self,
        aoi: dict,
        start: date,
        end: date,
        orbit: int,
        pass_dir: str,
    ) -> xr.Dataset:
        """Sentinel-1 GRD scenes over an AOI GeoJSON, fixed orbit/pass (FR-RS-1)."""

    @abstractmethod
    def get_dem(self, aoi: dict, asset: str = DEM_GLO30) -> xr.Dataset:
        """DEM raster over an AOI (volume + catchment + terrain correction)."""

    @abstractmethod
    def get_collection(
        self,
        asset_id: str,
        region: dict,
        start: date,
        end: date,
        bands: list[str],
    ) -> xr.Dataset:
        """Generic catchment-forcing pull (ERA5-Land/IMERG/GFS/MODIS) → xarray (FR-DE-8..10)."""

    @abstractmethod
    def list_scenes(
        self,
        asset_id: str,
        aoi: dict,
        start: date,
        end: date,
    ) -> list[dict]:
        """Scene metadata for nearest-match + freshness (FR-GT-1, NFR-TIME-1)."""


class GEEBackend(DataAccessBackend):
    """Google Earth Engine backend (geemap/xee). Credentials are loaded lazily so the
    class can be imported and type-checked without GEE installed or authenticated."""

    name = "gee"

    def __init__(self, project: str | None = None, key_file: str | None = None) -> None:
        self.project = project or os.environ.get("GEE_PROJECT")
        self.key_file = key_file or os.environ.get("GEE_SA_KEY_FILE")
        self._initialized = False

    def _ensure_init(self) -> None:
        if self._initialized:
            return
        try:
            import ee  # noqa: F401  (lazy; not a Phase 0 dependency)
        except ImportError as exc:  # pragma: no cover - exercised only with GEE installed
            raise RuntimeError(
                "GEEBackend requires the 'earthengine-api'/'geemap'/'xee' extras and a "
                "service-account key at GEE_SA_KEY_FILE. Use DATA_ACCESS_BACKEND=fixture "
                "for credential-free runs."
            ) from exc
        # Real ee.Initialize(...) wiring lands with the RS pipeline (Phase 2).
        self._initialized = True

    def get_s1_grd(self, aoi, start, end, orbit, pass_dir):  # pragma: no cover - Phase 2
        self._ensure_init()
        raise NotImplementedError("GEE Sentinel-1 retrieval lands in Phase 2 (RS pipeline).")

    def get_dem(self, aoi, asset=DEM_GLO30):  # pragma: no cover - Phase 2
        self._ensure_init()
        raise NotImplementedError("GEE DEM retrieval lands in Phase 2 (RS pipeline).")

    def get_collection(self, asset_id, region, start, end, bands):  # pragma: no cover - Phase 1
        self._ensure_init()
        raise NotImplementedError("GEE forcing retrieval lands in Phase 1 (DE pipeline).")

    def list_scenes(self, asset_id, aoi, start, end):  # pragma: no cover - Phase 2
        self._ensure_init()
        raise NotImplementedError("GEE scene listing lands in Phase 2 (RS pipeline).")


class FixtureBackend(DataAccessBackend):
    """Canned, credential-free backend for tests/CI. Returns small, deterministic
    ``xarray`` datasets and scene-metadata dicts shaped like the real outputs."""

    name = "fixture"

    def _grid(self, start: date, end: date, varname: str) -> xr.Dataset:
        import numpy as np
        import pandas as pd
        import xarray as xr

        times = pd.date_range(start, end, freq="D")
        lats = np.linspace(31.0, 32.0, 4)
        lons = np.linspace(76.0, 77.0, 4)
        data = np.zeros((len(times), len(lats), len(lons)), dtype="float32")
        return xr.Dataset(
            {varname: (("time", "lat", "lon"), data)},
            coords={"time": times, "lat": lats, "lon": lons},
        )

    def get_s1_grd(self, aoi, start, end, orbit, pass_dir):
        """Physically plausible S1 IW dB scene stack (not 0 dB everywhere): a specular
        water block (VH ≈ −22 dB) inside land clutter (VH ≈ −12 dB), VV ≈ VH + 5 dB,
        with mild noise. Deterministic so extractor tests are reproducible."""
        import numpy as np
        import pandas as pd
        import xarray as xr

        times = pd.date_range(start, end, freq="D")
        lats = np.linspace(31.0, 32.0, 16)
        lons = np.linspace(76.0, 77.0, 16)
        water = np.zeros((len(lats), len(lons)), dtype=bool)
        water[5:11, 4:12] = True  # reservoir pool near the grid centre
        rng = np.random.default_rng(42)
        shape = (len(times), len(lats), len(lons))
        vh = np.where(water, -22.0, -12.0) + rng.normal(0.0, 1.0, shape)
        vv = np.where(water, -17.0, -7.0) + rng.normal(0.0, 1.0, shape)
        ds = xr.Dataset(
            {
                "VH": (("time", "lat", "lon"), vh.astype("float32")),
                "VV": (("time", "lat", "lon"), vv.astype("float32")),
            },
            coords={"time": times, "lat": lats, "lon": lons},
        )
        ds.attrs.update(orbit_relative=orbit, pass_direction=pass_dir)
        return ds

    def get_dem(self, aoi, asset=DEM_GLO30):
        import numpy as np
        import xarray as xr

        lats = np.linspace(31.0, 32.0, 4)
        lons = np.linspace(76.0, 77.0, 4)
        dem = np.full((len(lats), len(lons)), 500.0, dtype="float32")
        return xr.Dataset(
            {"DEM": (("lat", "lon"), dem)},
            coords={"lat": lats, "lon": lons},
            attrs={"asset": asset},
        )

    def get_collection(self, asset_id, region, start, end, bands):
        ds = self._grid(start, end, bands[0] if bands else "value")
        ds.attrs["asset_id"] = asset_id
        return ds

    def list_scenes(self, asset_id, aoi, start, end):
        import pandas as pd

        return [
            {"scene_id": f"{asset_id}/{d:%Y%m%d}", "acquisition_date": d.date().isoformat()}
            for d in pd.date_range(start, end, freq="12D")
        ]


class OpenMeteoBackend(FixtureBackend):
    """Selector backend for Open-Meteo catchment forcing.

    The forcing pipeline handles Open-Meteo directly because it returns tabular daily
    catchment aggregates, not xarray rasters. Other data-access methods inherit the
    fixture implementation so non-forcing pipeline smoke tests remain credential-free.
    """

    name = "openmeteo"


_BACKENDS: dict[str, type[DataAccessBackend]] = {
    "gee": GEEBackend,
    "fixture": FixtureBackend,
    "openmeteo": OpenMeteoBackend,
}


def get_backend(name: str | None = None) -> DataAccessBackend:
    """Factory. Reads ``DATA_ACCESS_BACKEND`` when ``name`` is None (default ``gee``)."""
    key = (name or os.environ.get("DATA_ACCESS_BACKEND") or "gee").lower()
    try:
        return _BACKENDS[key]()
    except KeyError:
        raise ValueError(
            f"Unknown data-access backend {key!r}; valid: {sorted(_BACKENDS)}"
        ) from None
