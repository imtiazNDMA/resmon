"""DE pipeline orchestrator (plain Python — Prefect flow wrapper deferred to Phase 9).

Runs the bulletins→ABT spine end to end against the DB: seed → ingest (validated) →
stub observations → fuse → forcing → ABT (validated). Each step is idempotent
(upserts), so re-running is safe (§4.3). The Prefect ``@flow``/``@task`` wrapper and
the RS→DE→ML trigger chain land in Phase 9 (orchestration); the logic those tasks call
lives here.

``run_full_pipeline`` (orchestration) calls this with ``build_abt_stage=False`` and
rebuilds the ABT *after* the RS pipeline has written real observations, so the gold
table always reflects the same run's extractions.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from pipelines_common.dataaccess import DataAccessBackend, get_backend
from sqlalchemy import text
from sqlalchemy.orm import Session

from data_engineering.build_abt import build_abt
from data_engineering.forcing import aggregate_forcing
from data_engineering.fusion import fuse_observations_groundtruth
from data_engineering.ingest import ingest_bulletins
from data_engineering.reservoirs import REGISTRY
from data_engineering.seed import seed_reservoirs
from data_engineering.stub_observations import generate_stub_observations
from data_engineering.validation import validate_abt

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CSV = ROOT / "data" / "historical" / "reservoir_timeseries.csv"


def build_and_validate_abt(session: Session, reservoir_ids: list[str], abt_version: str) -> int:
    """Build the ABT, then run the gold-boundary pandera validation (AC-12) against the
    rows actually persisted for this version — fail loudly on any violation."""
    rows = build_abt(session, reservoir_ids, abt_version)
    abt_df = pd.read_sql(
        text(
            "SELECT reservoir_id, date, frl, live_capacity_bcm, gt_pct_filled, "
            "surface_area, row_quality FROM analytical_base_table WHERE abt_version = :v"
        ),
        session.connection(),
        params={"v": abt_version},
    )
    if not abt_df.empty:
        validate_abt(abt_df)
    return rows


def run_de_pipeline(
    session: Session,
    csv_path: str | Path = DEFAULT_CSV,
    abt_version: str = "abt_v1",
    backend: DataAccessBackend | None = None,
    forcing_start: date = date(2025, 5, 1),
    forcing_end: date = date(2026, 4, 30),
    build_abt_stage: bool = True,
) -> dict:
    """Run the full DE spine. Returns a summary of row counts per stage.

    ``build_abt_stage=False`` runs everything except the ABT build — used by the full
    orchestration so the ABT is built only after RS has written real observations.
    """
    backend = backend or get_backend()
    slugs = [m.slug for m in REGISTRY.values()]

    seeded = seed_reservoirs(session)
    counts = ingest_bulletins(session, csv_path)
    # Stub generation self-gates: reservoirs that already carry real (non-stub)
    # observations are skipped, and reruns can never overwrite a real row.
    stubs = generate_stub_observations(session)
    matches = fuse_observations_groundtruth(session)

    forcing_rows = 0
    forecast_rows = 0
    for slug in slugs:
        forcing_rows += aggregate_forcing(session, backend, slug, forcing_start, forcing_end)
    # Forecast forcing is intentionally not populated until a real GFS-backed path exists.
    # Writing plausible-looking zero rows here would train downstream models to ignore
    # weather forecasts and hide the missing integration.

    abt_rows = build_and_validate_abt(session, slugs, abt_version) if build_abt_stage else 0

    return {
        "reservoirs_seeded": seeded,
        **counts,
        "stub_observations": stubs,
        "ground_truth_matches": matches,
        "catchment_forcing_rows": forcing_rows,
        "forecast_forcing_rows": forecast_rows,
        "abt_rows": abt_rows,
        "abt_version": abt_version,
    }
