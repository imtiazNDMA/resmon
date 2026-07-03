"""Load Stage-1.2 backfill CSVs into ``observation`` (Replan.md data prerequisite).

Only ``status == 'ok'`` rows carry an area; abstain/error scenes are counted but never
loaded (a gap is honest, a fake area is not). Upsert converges on re-run and replaces
any stub row for the same (reservoir, date).

``aoi_version`` isn't in the CSV (frozen orbit/pass is, per scene-inventory recon) so
it's read from ``reservoir`` per file, mirroring the live-GEE upsert in
``scripts/populate_geometry.py``. No water-mask asset is persisted in batch mode
(``water_mask_ref`` is a provenance placeholder, ``water_mask_geom`` stays NULL) and
``layover_shadow_fraction`` is recorded as the same 0 *lower-bound placeholder* used
there, pending the terrain pipeline.

Run: uv run python scripts/load_backfill.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from core.db.session import session_scope
from remote_sensing.extractors import OtsuVH
from sqlalchemy import text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
BACKFILL_DIR = ROOT / "data" / "backfill"

_SEL_AOI_VERSION = text("SELECT aoi_version FROM reservoir WHERE reservoir_id = :rid")

_UPSERT = text(
    """
    INSERT INTO observation
        (reservoir_id, acquisition_date, surface_area, area_confidence, water_mask_ref,
         extraction_method, extraction_version, scene_ids, orbit_relative, pass_direction,
         aoi_version, layover_shadow_fraction, processing_params)
    VALUES
        (:rid, :date, :area, :conf, :water_mask_ref,
         :method, :version, ARRAY[:scene_id], :orbit, :pass_dir,
         :aoi_version, 0, CAST(:pp AS jsonb))
    ON CONFLICT (reservoir_id, acquisition_date) DO UPDATE SET
        surface_area = EXCLUDED.surface_area,
        area_confidence = EXCLUDED.area_confidence,
        water_mask_ref = EXCLUDED.water_mask_ref,
        extraction_method = EXCLUDED.extraction_method,
        extraction_version = EXCLUDED.extraction_version,
        scene_ids = EXCLUDED.scene_ids,
        orbit_relative = EXCLUDED.orbit_relative,
        pass_direction = EXCLUDED.pass_direction,
        aoi_version = EXCLUDED.aoi_version,
        processing_params = EXCLUDED.processing_params
    """
)


def load_backfill(session: Session, csv_dir: Path) -> dict[str, int]:
    """Upsert every ``status == 'ok'`` row from ``area_series_<slug>.csv`` files in
    ``csv_dir`` into ``observation``. Returns ``{"loaded": n, "skipped_non_ok": m}``."""
    loaded = skipped = 0
    for csv_path in sorted(csv_dir.glob("area_series_*.csv")):
        rid = csv_path.stem.removeprefix("area_series_")
        aoi_version = session.execute(_SEL_AOI_VERSION, {"rid": rid}).scalar_one()
        with csv_path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row["status"] != "ok" or not row["area_km2"]:
                    skipped += 1
                    continue
                session.execute(
                    _UPSERT,
                    {
                        "rid": rid,
                        "date": row["acquisition_date"],
                        "area": float(row["area_km2"]),
                        # v1 confidence = separability (compactness/layover unavailable
                        # in batch mode; documented in Replan.md)
                        "conf": float(row["separability"]),
                        "water_mask_ref": f"backfill://{row['scene_id']}",
                        "method": OtsuVH.name,
                        "version": OtsuVH.version,
                        "scene_id": row["scene_id"],
                        "orbit": int(row["orbit_relative"]),
                        "pass_dir": row["pass_direction"],
                        "aoi_version": aoi_version,
                        "pp": json.dumps(
                            {
                                "threshold_db": float(row["threshold_db"]),
                                "otsu_eta": float(row["otsu_eta"]),
                                "valley_ratio": float(row["valley_ratio"]),
                            }
                        ),
                    },
                )
                loaded += 1
    return {"loaded": loaded, "skipped_non_ok": skipped}


def main() -> int:
    with session_scope() as session:
        result = load_backfill(session, BACKFILL_DIR)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
