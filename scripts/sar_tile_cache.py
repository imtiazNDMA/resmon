"""Report and prune the rendered SAR PNG tile cache.

Run:
  uv run python scripts/sar_tile_cache.py --stats
  uv run python scripts/sar_tile_cache.py --cleanup-max-mb 512
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from api import gee_tiles


def _format_mb(bytes_: int) -> str:
    return f"{bytes_ / (1024 * 1024):.2f} MB"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None, help="override raster cache root")
    parser.add_argument("--stats", action="store_true", help="print current cache usage")
    parser.add_argument(
        "--cleanup-max-mb",
        type=float,
        help="delete oldest cached PNG tiles until cache is at or below this size",
    )
    args = parser.parse_args(argv)

    if not args.stats and args.cleanup_max_mb is None:
        parser.error("one of --stats or --cleanup-max-mb is required")

    try:
        if args.cleanup_max_mb is not None:
            stats = gee_tiles.cleanup_raster_cache(
                int(args.cleanup_max_mb * 1024 * 1024), root=args.root
            )
            print(
                f"cache cleanup: root={stats.root} tiles={stats.tiles} "
                f"size={_format_mb(stats.bytes)}"
            )
        if args.stats:
            stats = gee_tiles.raster_cache_stats(root=args.root)
            print(
                f"cache stats: root={stats.root} tiles={stats.tiles} "
                f"size={_format_mb(stats.bytes)}"
            )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
