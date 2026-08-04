"""Pre-render local SAR XYZ tiles into the API PNG cache.

Run:
  uv run python scripts/prewarm_sar_tiles.py --reservoir pong --date 2020-01-05 \
    --composite vh --min-zoom 8 --max-zoom 10
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from api.sar_assets import SarAsset

from api import gee_tiles, sar_assets

TileRenderer = Callable[[SarAsset, str, int, int, int], bytes]
CacheWriter = Callable[[str, str, str, int, int, int, bytes], None]


@dataclass(frozen=True)
class PrewarmResult:
    reservoir_id: str
    acquisition_date: str
    composite: str
    tiles: int
    rendered: int
    skipped: int


def prewarm_demo_tiles(
    *,
    reservoir_id: str,
    composite: str,
    min_zoom: int,
    max_zoom: int,
    nearby_dates: int = 2,
    catalog_path: Path | None = None,
    dry_run: bool = False,
    renderer: TileRenderer = sar_assets.render_tile,
    cache_writer: CacheWriter = gee_tiles.put_cached_raster_content,
) -> list[PrewarmResult]:
    """Prewarm the latest local acquisition plus nearby prior timeline dates."""
    composite = gee_tiles.validate_composite(composite)
    entries = [
        entry
        for entry in sar_assets.list_manifest(reservoir_id, catalog_path)
        if composite in entry.composites
    ]
    dates = sorted({entry.acquisition_date for entry in entries})
    if not dates:
        raise ValueError(f"no local manifest entries for {reservoir_id} composite {composite}")
    selected_dates = dates[-(nearby_dates + 1) :]
    return [
        prewarm_tiles(
            reservoir_id=reservoir_id,
            acquisition_date=date,
            composite=composite,
            min_zoom=min_zoom,
            max_zoom=max_zoom,
            catalog_path=catalog_path,
            dry_run=dry_run,
            renderer=renderer,
            cache_writer=cache_writer,
        )
        for date in selected_dates
    ]


def prewarm_tiles(
    *,
    reservoir_id: str,
    acquisition_date: str,
    composite: str,
    min_zoom: int,
    max_zoom: int,
    catalog_path: Path | None = None,
    dry_run: bool = False,
    renderer: TileRenderer = sar_assets.render_tile,
    cache_writer: CacheWriter = gee_tiles.put_cached_raster_content,
) -> PrewarmResult:
    """Render every tile intersecting the local SAR asset bounds for a zoom range."""
    if min_zoom > max_zoom:
        raise ValueError("--min-zoom cannot be greater than --max-zoom")
    composite = gee_tiles.validate_composite(composite)
    asset = sar_assets.find_asset(
        reservoir_id,
        acquisition_date,
        composite,
        catalog_path or sar_assets._CATALOG_PATH,
    )
    if asset is None:
        raise ValueError(
            f"no ready local asset for {reservoir_id} {acquisition_date} composite {composite}"
        )
    if asset.bounds is None:
        raise ValueError(f"local asset has no bounds: {reservoir_id} {acquisition_date}")

    tiles = list(_tiles_for_bounds(asset.bounds, min_zoom, max_zoom))
    rendered = 0
    skipped = 0
    for z, x, y in tiles:
        if gee_tiles.get_cached_raster_content(reservoir_id, acquisition_date, composite, z, x, y):
            skipped += 1
            continue
        if dry_run:
            continue
        content = renderer(asset, composite, z, x, y)
        cache_writer(reservoir_id, acquisition_date, composite, z, x, y, content)
        rendered += 1
    return PrewarmResult(reservoir_id, acquisition_date, composite, len(tiles), rendered, skipped)


def _tiles_for_bounds(
    bounds: tuple[float, float, float, float], min_zoom: int, max_zoom: int
) -> list[tuple[int, int, int]]:
    min_lon, min_lat, max_lon, max_lat = bounds
    tiles: list[tuple[int, int, int]] = []
    for z in range(min_zoom, max_zoom + 1):
        min_x, max_y = _lonlat_to_tile(min_lon, min_lat, z)
        max_x, min_y = _lonlat_to_tile(max_lon, max_lat, z)
        for x in range(min(min_x, max_x), max(min_x, max_x) + 1):
            for y in range(min(min_y, max_y), max(min_y, max_y) + 1):
                tiles.append((z, x, y))
    return tiles


def _lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reservoir", required=True, help="reservoir id/slug")
    parser.add_argument("--date", help="SAR acquisition date, YYYY-MM-DD")
    parser.add_argument("--composite", default=gee_tiles.DEFAULT_COMPOSITE)
    parser.add_argument("--min-zoom", type=int, required=True)
    parser.add_argument("--max-zoom", type=int, required=True)
    parser.add_argument("--catalog", type=Path, default=None, help="override catalog SQLite path")
    parser.add_argument(
        "--latest-nearby",
        type=int,
        metavar="N",
        help="prewarm the latest local date plus N nearby prior timeline dates",
    )
    parser.add_argument("--dry-run", action="store_true", help="count tiles without rendering")
    args = parser.parse_args(argv)

    try:
        if args.latest_nearby is not None:
            results = prewarm_demo_tiles(
                reservoir_id=args.reservoir,
                composite=args.composite,
                min_zoom=args.min_zoom,
                max_zoom=args.max_zoom,
                nearby_dates=args.latest_nearby,
                catalog_path=args.catalog,
                dry_run=args.dry_run,
            )
        else:
            if args.date is None:
                raise ValueError("--date is required unless --latest-nearby is used")
            results = [
                prewarm_tiles(
                    reservoir_id=args.reservoir,
                    acquisition_date=args.date,
                    composite=args.composite,
                    min_zoom=args.min_zoom,
                    max_zoom=args.max_zoom,
                    catalog_path=args.catalog,
                    dry_run=args.dry_run,
                )
            ]
    except (ValueError, sar_assets.LocalSarUnavailable) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    action = "would prewarm" if args.dry_run else "prewarmed"
    for result in results:
        print(
            f"{action}: {result.reservoir_id} {result.acquisition_date} {result.composite} "
            f"tiles={result.tiles} rendered={result.rendered} skipped={result.skipped}"
        )
    if len(results) > 1:
        print(
            "total: "
            f"dates={len(results)} tiles={sum(r.tiles for r in results)} "
            f"rendered={sum(r.rendered for r in results)} skipped={sum(r.skipped for r in results)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
