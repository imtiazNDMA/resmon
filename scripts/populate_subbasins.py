"""Populate only HydroBASINS sub-basin topology rows.

This is the fast repair path when `/geojson/subbasins` is empty but catchment geometry
already exists. It does not rerun AOI derivation, Sentinel-1 extraction, or estimation.

Run all pilots:
    uv run python scripts/populate_subbasins.py

Run one reservoir:
    uv run python scripts/populate_subbasins.py --reservoir pong
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("GEE_SA_KEY_FILE", "geeservice.json")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.db.session import make_engine  # noqa: E402
from data_engineering.reservoirs import REGISTRY  # noqa: E402
from remote_sensing.gee_real import GeeExtractionError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from scripts.populate_geometry import populate_subbasins_for_meta  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("populate_subbasins")


def _registry_by_slug():
    return {meta.slug: meta for meta in REGISTRY.values()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Populate real HydroBASINS sub-basins")
    parser.add_argument("--reservoir", choices=sorted(_registry_by_slug()), help="reservoir_id")
    args = parser.parse_args()

    metas = _registry_by_slug()
    selected = [metas[args.reservoir]] if args.reservoir else list(metas.values())

    failures = 0
    with Session(make_engine()) as session:
        for meta in selected:
            print(f"[{meta.slug}] HydroBASINS sub-basins ...", flush=True)
            try:
                count = populate_subbasins_for_meta(session, meta.slug, meta.dam_lon, meta.dam_lat)
            except GeeExtractionError as exc:
                failures += 1
                session.rollback()
                log.error("[%s] failed: %s", meta.slug, exc)
                continue
            print(f"  OK {meta.slug}: {count} sub-basins", flush=True)

    if failures:
        raise SystemExit(f"{failures} reservoir(s) failed; see log above")
    print("Sub-basin populate complete.")


if __name__ == "__main__":
    main()
