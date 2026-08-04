"""Local SAR asset catalog.

The catalog records where local georeferenced SAR rasters live. It intentionally
does not store pixel bytes; COG files stay on disk and rendered PNG tiles use the
existing tile cache path.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sqlite3
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CATALOG_PATH = _REPO_ROOT / ".cache" / "sar_assets.sqlite"


@dataclass(frozen=True)
class SarAsset:
    reservoir_id: str
    acquisition_date: str
    scene_id: str
    vv_path: Path | None
    vh_path: Path | None
    water_mask_path: Path | None
    bounds: tuple[float, float, float, float] | None
    min_zoom: int
    max_zoom: int
    status: str
    vv_size_bytes: int | None = None
    vv_sha256: str | None = None
    vh_size_bytes: int | None = None
    vh_sha256: str | None = None
    water_mask_size_bytes: int | None = None
    water_mask_sha256: str | None = None


@dataclass(frozen=True)
class SarAssetManifestEntry:
    reservoir_id: str
    acquisition_date: str
    scene_id: str
    composites: tuple[str, ...]
    bounds: tuple[float, float, float, float] | None
    min_zoom: int
    max_zoom: int


class LocalSarUnavailable(RuntimeError):
    """Local SAR assets exist, but no local raster tile can be produced yet."""


def init_catalog(db_path: Path = _CATALOG_PATH) -> None:
    """Create the local SAR catalog table if it does not exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sar_asset (
                reservoir_id TEXT NOT NULL,
                acquisition_date TEXT NOT NULL,
                scene_id TEXT NOT NULL,
                vv_path TEXT,
                vh_path TEXT,
                water_mask_path TEXT,
                min_lon REAL,
                min_lat REAL,
                max_lon REAL,
                max_lat REAL,
                min_zoom INTEGER NOT NULL DEFAULT 8,
                max_zoom INTEGER NOT NULL DEFAULT 14,
                status TEXT NOT NULL DEFAULT 'ready',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (reservoir_id, acquisition_date, scene_id)
            )
            """
        )
        _ensure_catalog_columns(conn)


def upsert_asset(
    asset: SarAsset,
    db_path: Path = _CATALOG_PATH,
) -> None:
    """Insert or replace a local SAR asset catalog row."""
    init_catalog(db_path)
    bounds = asset.bounds or (None, None, None, None)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sar_asset (
                reservoir_id,
                acquisition_date,
                scene_id,
                vv_path,
                vh_path,
                water_mask_path,
                min_lon,
                min_lat,
                max_lon,
                max_lat,
                min_zoom,
                max_zoom,
                status,
                vv_size_bytes,
                vv_sha256,
                vh_size_bytes,
                vh_sha256,
                water_mask_size_bytes,
                water_mask_sha256,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (reservoir_id, acquisition_date, scene_id) DO UPDATE SET
                vv_path = excluded.vv_path,
                vh_path = excluded.vh_path,
                water_mask_path = excluded.water_mask_path,
                min_lon = excluded.min_lon,
                min_lat = excluded.min_lat,
                max_lon = excluded.max_lon,
                max_lat = excluded.max_lat,
                min_zoom = excluded.min_zoom,
                max_zoom = excluded.max_zoom,
                status = excluded.status,
                vv_size_bytes = excluded.vv_size_bytes,
                vv_sha256 = excluded.vv_sha256,
                vh_size_bytes = excluded.vh_size_bytes,
                vh_sha256 = excluded.vh_sha256,
                water_mask_size_bytes = excluded.water_mask_size_bytes,
                water_mask_sha256 = excluded.water_mask_sha256,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                asset.reservoir_id,
                asset.acquisition_date,
                asset.scene_id,
                str(asset.vv_path) if asset.vv_path else None,
                str(asset.vh_path) if asset.vh_path else None,
                str(asset.water_mask_path) if asset.water_mask_path else None,
                *bounds,
                asset.min_zoom,
                asset.max_zoom,
                asset.status,
                asset.vv_size_bytes,
                asset.vv_sha256,
                asset.vh_size_bytes,
                asset.vh_sha256,
                asset.water_mask_size_bytes,
                asset.water_mask_sha256,
            ),
        )


def find_asset(
    reservoir_id: str,
    acquisition_date: str,
    composite: str,
    db_path: Path = _CATALOG_PATH,
) -> SarAsset | None:
    """Return a ready local asset if the files needed by ``composite`` exist."""
    if not db_path.exists():
        return None
    init_catalog(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT * FROM sar_asset
            WHERE reservoir_id = ? AND acquisition_date = ? AND status = 'ready'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (reservoir_id, acquisition_date),
        ).fetchone()
    if row is None:
        return None
    asset = _row_to_asset(row)
    return asset if _has_composite_files(asset, composite) and validate_asset_files(asset) else None


def list_manifest(
    reservoir_id: str | None = None,
    db_path: Path | None = None,
) -> list[SarAssetManifestEntry]:
    """List ready local SAR assets and the composites renderable from local files."""
    db_path = db_path or _CATALOG_PATH
    if not db_path.exists():
        return []
    init_catalog(db_path)
    where = "WHERE status = 'ready'"
    params: tuple[str, ...] = ()
    if reservoir_id is not None:
        where += " AND reservoir_id = ?"
        params = (reservoir_id,)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT * FROM sar_asset
            {where}
            ORDER BY reservoir_id, acquisition_date, scene_id
            """,
            params,
        ).fetchall()
    entries = []
    for row in rows:
        asset = _row_to_asset(row)
        composites = tuple(
            composite
            for composite in ("vh", "vv", "false_color", "water_class", "vv_vh_contrast")
            if _has_composite_files(asset, composite)
        )
        if composites and validate_asset_files(asset):
            entries.append(
                SarAssetManifestEntry(
                    reservoir_id=asset.reservoir_id,
                    acquisition_date=asset.acquisition_date,
                    scene_id=asset.scene_id,
                    composites=composites,
                    bounds=asset.bounds,
                    min_zoom=asset.min_zoom,
                    max_zoom=asset.max_zoom,
                )
            )
    return entries


def render_tile(
    asset: SarAsset,
    composite: str,
    z: int,
    x: int,
    y: int,
) -> bytes:
    """Render one XYZ PNG tile from local SAR rasters."""
    try:
        configure_rasterio_environment()
        import numpy as np  # noqa: PLC0415
        import rasterio  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415
        from rasterio.enums import Resampling  # noqa: PLC0415
        from rasterio.warp import reproject  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - exercised by deploy environments
        raise LocalSarUnavailable("local SAR rendering dependencies are unavailable") from exc

    tile_bounds = _xyz_bounds_3857(z, x, y)
    transform = rasterio.transform.from_bounds(*tile_bounds, 256, 256)

    def read_band(path: Path, *, categorical: bool = False):
        destination = np.full((256, 256), np.nan, dtype="float32")
        with rasterio.open(path) as src:
            reproject(
                source=rasterio.band(src, 1),
                destination=destination,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=src.nodata,
                dst_transform=transform,
                dst_crs="EPSG:3857",
                dst_nodata=np.nan,
                resampling=Resampling.nearest if categorical else Resampling.bilinear,
            )
        return destination

    if composite == "vh":
        if asset.vh_path is None:
            raise LocalSarUnavailable("VH raster path is missing")
        rgb, alpha = _grayscale_rgba(read_band(asset.vh_path), -25.0, -5.0, np)
    elif composite == "vv":
        if asset.vv_path is None:
            raise LocalSarUnavailable("VV raster path is missing")
        rgb, alpha = _grayscale_rgba(read_band(asset.vv_path), -20.0, 0.0, np)
    elif composite in {"false_color", "vv_vh_contrast"}:
        if asset.vv_path is None or asset.vh_path is None:
            raise LocalSarUnavailable("VV/VH raster paths are missing")
        vv = read_band(asset.vv_path)
        vh = read_band(asset.vh_path)
        diff = vv - vh
        if composite == "false_color":
            mins = (-24.0, -30.0, 0.0)
            maxs = (0.0, -4.0, 14.0)
        else:
            mins = (-22.0, -28.0, 0.0)
            maxs = (0.0, -4.0, 12.0)
        bands = [
            _scale_to_byte(arr, lo, hi, np)
            for arr, lo, hi in zip((vv, vh, diff), mins, maxs, strict=True)
        ]
        rgb = np.dstack(bands).astype("uint8")
        alpha = np.where(np.isfinite(vv) & np.isfinite(vh), 255, 0).astype("uint8")
    elif composite == "water_class":
        if asset.water_mask_path is None:
            raise LocalSarUnavailable("water-mask raster path is missing")
        mask = read_band(asset.water_mask_path, categorical=True)
        alpha = np.where(np.isfinite(mask), 255, 0).astype("uint8")
        water = mask >= 0.5
        rgb = np.zeros((256, 256, 3), dtype="uint8")
        rgb[..., 0] = np.where(water, 0x00, 0x2E)
        rgb[..., 1] = np.where(water, 0x47, 0xEF)
        rgb[..., 2] = np.where(water, 0xFF, 0x35)
    else:
        raise LocalSarUnavailable(f"unsupported SAR composite {composite!r}")

    rgba = np.dstack((rgb, alpha)).astype("uint8")
    out = BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(out, format="PNG")
    return out.getvalue()


def configure_rasterio_environment() -> None:
    """Prefer Rasterio's bundled PROJ data over system PostGIS/GDAL installs.

    Some Windows machines expose an older PostGIS ``proj.db`` through ``PROJ_LIB``;
    Rasterio wheels ship their own matching PROJ database and should use that.
    """
    spec = importlib.util.find_spec("rasterio")
    if spec is None or spec.origin is None:
        return
    proj_data = Path(spec.origin).parent / "proj_data"
    if proj_data.exists():
        os.environ["PROJ_LIB"] = str(proj_data)


def file_metadata(path: Path) -> tuple[int, str]:
    """Return byte size and SHA-256 for a local SAR raster."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def validate_asset_files(asset: SarAsset) -> bool:
    """Check recorded size/checksum metadata against files on disk when present."""
    checks = (
        (asset.vv_path, asset.vv_size_bytes, asset.vv_sha256),
        (asset.vh_path, asset.vh_size_bytes, asset.vh_sha256),
        (asset.water_mask_path, asset.water_mask_size_bytes, asset.water_mask_sha256),
    )
    for path, expected_size, expected_sha in checks:
        if path is None or expected_size is None or expected_sha is None:
            continue
        try:
            actual_size, actual_sha = file_metadata(path)
        except OSError:
            return False
        if actual_size != expected_size or actual_sha != expected_sha:
            return False
    return True


def _ensure_catalog_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(sar_asset)")}
    columns = {
        "vv_size_bytes": "INTEGER",
        "vv_sha256": "TEXT",
        "vh_size_bytes": "INTEGER",
        "vh_sha256": "TEXT",
        "water_mask_size_bytes": "INTEGER",
        "water_mask_sha256": "TEXT",
    }
    for name, column_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE sar_asset ADD COLUMN {name} {column_type}")


def _xyz_bounds_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    origin = 20037508.342789244
    tile_size = origin * 2 / (2**z)
    left = -origin + x * tile_size
    right = left + tile_size
    top = origin - y * tile_size
    bottom = top - tile_size
    return left, bottom, right, top


def _scale_to_byte(values, min_value: float, max_value: float, np):
    scaled = (values - min_value) / (max_value - min_value)
    scaled = np.clip(scaled, 0.0, 1.0)
    return np.nan_to_num(scaled * 255.0, nan=0.0).astype("uint8")


def _grayscale_rgba(values, min_value: float, max_value: float, np):
    gray = _scale_to_byte(values, min_value, max_value, np)
    rgb = np.dstack((gray, gray, gray)).astype("uint8")
    alpha = np.where(np.isfinite(values), 255, 0).astype("uint8")
    return rgb, alpha


def _row_to_asset(row: sqlite3.Row) -> SarAsset:
    bounds = None
    if all(row[key] is not None for key in ("min_lon", "min_lat", "max_lon", "max_lat")):
        bounds = (
            float(row["min_lon"]),
            float(row["min_lat"]),
            float(row["max_lon"]),
            float(row["max_lat"]),
        )
    return SarAsset(
        reservoir_id=str(row["reservoir_id"]),
        acquisition_date=str(row["acquisition_date"]),
        scene_id=str(row["scene_id"]),
        vv_path=_path_or_none(row["vv_path"]),
        vh_path=_path_or_none(row["vh_path"]),
        water_mask_path=_path_or_none(row["water_mask_path"]),
        bounds=bounds,
        min_zoom=int(row["min_zoom"]),
        max_zoom=int(row["max_zoom"]),
        status=str(row["status"]),
        vv_size_bytes=_int_or_none(row["vv_size_bytes"]),
        vv_sha256=row["vv_sha256"],
        vh_size_bytes=_int_or_none(row["vh_size_bytes"]),
        vh_sha256=row["vh_sha256"],
        water_mask_size_bytes=_int_or_none(row["water_mask_size_bytes"]),
        water_mask_sha256=row["water_mask_sha256"],
    )


def _path_or_none(value: str | None) -> Path | None:
    return Path(value) if value else None


def _int_or_none(value: int | None) -> int | None:
    return int(value) if value is not None else None


def _has_composite_files(asset: SarAsset, composite: str) -> bool:
    requirements = {
        "vh": (asset.vh_path,),
        "vv": (asset.vv_path,),
        "false_color": (asset.vv_path, asset.vh_path),
        "vv_vh_contrast": (asset.vv_path, asset.vh_path),
        "water_class": (asset.water_mask_path,),
    }
    paths = requirements.get(composite)
    if paths is None:
        return False
    return all(path is not None and path.exists() for path in paths)
