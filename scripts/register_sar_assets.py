"""Register local SAR GeoTIFF assets in the API tile catalog.

This is the first Phase-4 ingestion step: it does not download from Earth Engine.
It validates existing local VV/VH/water-mask rasters and records their paths so the
API can render zoomable SAR tiles locally.

Run:
  uv run python scripts/register_sar_assets.py --reservoir pong --date 2020-01-05 \
    --scene-id S1A_TEST --vv data/sar_cog/pong/2020-01-05/vv.tif \
    --vh data/sar_cog/pong/2020-01-05/vh.tif
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from api.sar_assets import SarAsset, configure_rasterio_environment, file_metadata, upsert_asset


def register_asset(
    *,
    reservoir_id: str,
    acquisition_date: str,
    scene_id: str,
    vv_path: Path | None = None,
    vh_path: Path | None = None,
    water_mask_path: Path | None = None,
    min_zoom: int = 8,
    max_zoom: int = 14,
    catalog_path: Path | None = None,
    dry_run: bool = False,
) -> SarAsset:
    """Validate local rasters and optionally upsert the catalog row."""
    paths = [p for p in (vv_path, vh_path, water_mask_path) if p is not None]
    if not paths:
        raise ValueError("at least one of --vv, --vh, or --water-mask is required")
    if min_zoom > max_zoom:
        raise ValueError("--min-zoom cannot be greater than --max-zoom")

    bounds = None
    metadata: dict[str, tuple[int, str]] = {}
    for path in paths:
        raster_bounds = _validate_raster(path)
        bounds = raster_bounds if bounds is None else _merge_bounds(bounds, raster_bounds)
        metadata[str(path)] = file_metadata(path)

    vv_meta = metadata.get(str(vv_path)) if vv_path is not None else None
    vh_meta = metadata.get(str(vh_path)) if vh_path is not None else None
    water_mask_meta = metadata.get(str(water_mask_path)) if water_mask_path is not None else None

    asset = SarAsset(
        reservoir_id=reservoir_id,
        acquisition_date=acquisition_date,
        scene_id=scene_id,
        vv_path=vv_path,
        vh_path=vh_path,
        water_mask_path=water_mask_path,
        bounds=bounds,
        min_zoom=min_zoom,
        max_zoom=max_zoom,
        status="ready",
        vv_size_bytes=vv_meta[0] if vv_meta else None,
        vv_sha256=vv_meta[1] if vv_meta else None,
        vh_size_bytes=vh_meta[0] if vh_meta else None,
        vh_sha256=vh_meta[1] if vh_meta else None,
        water_mask_size_bytes=water_mask_meta[0] if water_mask_meta else None,
        water_mask_sha256=water_mask_meta[1] if water_mask_meta else None,
    )
    if not dry_run:
        upsert_asset(asset, catalog_path) if catalog_path else upsert_asset(asset)
    return asset


def _validate_raster(path: Path) -> tuple[float, float, float, float]:
    if not path.exists():
        raise ValueError(f"raster file does not exist: {path}")
    try:
        configure_rasterio_environment()
        import rasterio  # noqa: PLC0415
        from rasterio.warp import transform_bounds  # noqa: PLC0415

        with rasterio.open(path) as src:
            if src.count < 1:
                raise ValueError(f"raster has no bands: {path}")
            if src.crs is None:
                raise ValueError(f"raster has no CRS: {path}")
            bounds = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
            return (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"invalid raster {path}: {exc}") from exc


def _merge_bounds(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def _path_arg(value: str | None) -> Path | None:
    return Path(value) if value else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reservoir", required=True, help="reservoir id/slug")
    parser.add_argument("--date", required=True, help="SAR acquisition date, YYYY-MM-DD")
    parser.add_argument("--scene-id", required=True, help="Sentinel-1 scene id")
    parser.add_argument("--vv", help="local VV GeoTIFF/COG path")
    parser.add_argument("--vh", help="local VH GeoTIFF/COG path")
    parser.add_argument("--water-mask", help="local water-mask GeoTIFF/COG path")
    parser.add_argument("--min-zoom", type=int, default=8)
    parser.add_argument("--max-zoom", type=int, default=14)
    parser.add_argument("--catalog", type=Path, default=None, help="override catalog SQLite path")
    parser.add_argument(
        "--dry-run", action="store_true", help="validate only; do not write catalog"
    )
    args = parser.parse_args(argv)

    try:
        asset = register_asset(
            reservoir_id=args.reservoir,
            acquisition_date=args.date,
            scene_id=args.scene_id,
            vv_path=_path_arg(args.vv),
            vh_path=_path_arg(args.vh),
            water_mask_path=_path_arg(args.water_mask),
            min_zoom=args.min_zoom,
            max_zoom=args.max_zoom,
            catalog_path=args.catalog,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    action = "validated" if args.dry_run else "registered"
    print(f"{action}: {asset.reservoir_id} {asset.acquisition_date} {asset.scene_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
