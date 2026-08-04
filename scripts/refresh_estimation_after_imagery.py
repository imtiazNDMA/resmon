"""Refresh estimation artifacts after SAR imagery rows have been loaded.

Startup loads/fetches imagery after the bootstrap pipeline has already fitted an initial
rating curve. This script re-runs the downstream estimation bridge against the imagery
currently in ``observation``:

1. match observations to bulletin ground truth;
2. fit active rating curves, preferring real SAR/backfill pairs over synthetic pairs;
3. rebuild the ABT so it carries the refreshed derived storage/level values.

Run after ``scripts/load_backfill.py`` and after any live GEE latest-imagery refresh.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.db.session import session_scope
from data_engineering.fusion import fuse_observations_groundtruth
from data_engineering.pipeline import build_and_validate_abt
from data_engineering.reservoirs import REGISTRY
from ml.groundtruthing import run_ground_truthing
from remote_sensing.extractors import OtsuVH


def main() -> int:
    version = "rc_imagery_refresh_" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    with session_scope() as session:
        matches = fuse_observations_groundtruth(session)
        gt = run_ground_truthing(session, version=version, extraction_method=OtsuVH.name)
        expected = len(REGISTRY)
        if gt["curves_persisted"] != expected:
            missing = ", ".join(gt["skipped"])
            raise RuntimeError(
                f"calibration incomplete: {gt['curves_persisted']}/{expected} curves persisted"
                + (f"; skipped: {missing}" if missing else "")
            )
        abt_rows = build_and_validate_abt(
            session, [meta.slug for meta in REGISTRY.values()], "abt_v1"
        )
    print("Estimation refresh complete:")
    print(f"  ground-truth matches : {matches}")
    print(f"  rating-curve version : {version}")
    print(f"  curves persisted     : {gt['curves_persisted']}")
    print(f"  AC-2 passed          : {gt['ac2_passed']}")
    print(f"  worst fill MAE       : {gt['ac2_worst_mae']:.3f}%")
    print(f"  synthetic data       : {gt['on_synthetic_data']}")
    print(f"  ABT rows             : {abt_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
