"""Stage-1.2 backfill driver: dense SAR area(t) series per reservoir (Replan.md §3).

Chunked, crash-safe, resumable: appends to ``data/backfill/area_series_<slug>.csv``
after every chunk and skips scene ids already present on restart. The AOI is derived
once per reservoir and cached (``data/backfill/aoi_<slug>.geojson``) so the series
geometry can never drift between runs.

Run:  uv run python scripts/backfill_extraction.py [--reservoir SLUG] [--chunk-size N]
      [--limit N]   (--limit is for smoke tests: process at most N scenes per reservoir)
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from dataclasses import asdict
from pathlib import Path

from data_engineering.reservoirs import REGISTRY
from remote_sensing.backfill import (
    CSV_COLUMNS,
    list_scene_ids,
    load_or_derive_aoi,
    process_chunk,
)

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "backfill"

log = logging.getLogger("backfill")


def done_scene_ids(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()
    with csv_path.open(encoding="utf-8", newline="") as fh:
        return {row["scene_id"] for row in csv.DictReader(fh)}


def append_rows(csv_path: Path, rows: list[dict]) -> None:
    new_file = not csv_path.exists()
    with csv_path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        if new_file:
            writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in CSV_COLUMNS})


def run_reservoir(slug: str, chunk_size: int, limit: int | None) -> dict[str, int]:
    meta = next(m for m in REGISTRY.values() if m.slug == slug)
    csv_path = OUT_DIR / f"area_series_{slug}.csv"
    aoi = load_or_derive_aoi(slug, meta.dam_lon, meta.dam_lat, OUT_DIR)

    ids = list_scene_ids(aoi, meta.orbit_relative, meta.pass_direction)
    done = done_scene_ids(csv_path)
    todo = [i for i in ids if i not in done]
    if limit is not None:
        todo = todo[:limit]
    log.info(
        "[%s] %d qualifying scenes, %d already done, %d to process",
        slug,
        len(ids),
        len(done),
        len(todo),
    )

    tally = {"ok": 0, "abstain": 0, "error": 0}
    for start in range(0, len(todo), chunk_size):
        chunk = todo[start : start + chunk_size]
        t0 = time.monotonic()
        results = process_chunk(aoi, meta.orbit_relative, meta.pass_direction, chunk)
        append_rows(csv_path, [asdict(r) for r in results])
        for r in results:
            tally[r.status] = tally.get(r.status, 0) + 1
        log.info(
            "[%s] chunk %d-%d/%d done in %.0fs (ok=%d abstain=%d error=%d)",
            slug,
            start + 1,
            start + len(chunk),
            len(todo),
            time.monotonic() - t0,
            tally["ok"],
            tally["abstain"],
            tally["error"],
        )
    return tally


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reservoir", choices=sorted(m.slug for m in REGISTRY.values()))
    parser.add_argument("--chunk-size", type=int, default=20)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    slugs = [args.reservoir] if args.reservoir else sorted(m.slug for m in REGISTRY.values())
    grand = {"ok": 0, "abstain": 0, "error": 0}
    for slug in slugs:
        tally = run_reservoir(slug, args.chunk_size, args.limit)
        for k, v in tally.items():
            grand[k] = grand.get(k, 0) + v
    log.info("backfill pass complete: %s", grand)
    return 0 if grand["error"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
