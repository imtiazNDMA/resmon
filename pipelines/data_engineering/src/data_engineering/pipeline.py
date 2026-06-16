"""DE pipeline orchestrator (plain Python — Prefect flow wrapper deferred to Phase 9).

Runs the bulletins→ABT spine end to end against the DB: seed → ingest → stub
observations → fuse → forcing → ABT. Each step is idempotent (upserts), so re-running is
safe (§4.3). The Prefect ``@flow``/``@task`` wrapper and the RS→DE→ML trigger chain land
in Phase 9 (orchestration); the logic those tasks call lives here.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pipelines_common.dataaccess import DataAccessBackend, get_backend
from sqlalchemy.orm import Session

from data_engineering.build_abt import build_abt
from data_engineering.forcing import aggregate_forcing, build_forecast_forcing
from data_engineering.fusion import fuse_observations_groundtruth
from data_engineering.ingest import ingest_bulletins
from data_engineering.reservoirs import REGISTRY
from data_engineering.seed import seed_reservoirs
from data_engineering.stub_observations import generate_stub_observations

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CSV = ROOT / "data" / "historical" / "reservoir_timeseries.csv"


def run_de_pipeline(
    session: Session,
    csv_path: str | Path = DEFAULT_CSV,
    abt_version: str = "abt_v1",
    backend: DataAccessBackend | None = None,
    forcing_start: date = date(2025, 5, 1),
    forcing_end: date = date(2026, 4, 30),
) -> dict:
    """Run the full DE spine. Returns a summary of row counts per stage."""
    backend = backend or get_backend()
    slugs = [m.slug for m in REGISTRY.values()]

    seeded = seed_reservoirs(session)
    counts = ingest_bulletins(session, csv_path)
    stubs = generate_stub_observations(session)
    matches = fuse_observations_groundtruth(session)

    forcing_rows = 0
    forecast_rows = 0
    for slug in slugs:
        forcing_rows += aggregate_forcing(session, backend, slug, forcing_start, forcing_end)
    # forecast forcing over the in-range bulletin issue dates (cheap subset of the spine)
    issue_dates = [
        d for d in (forcing_start, forcing_end)
    ]  # minimal seed; full set built in serving (Phase 9)
    for slug in slugs:
        forecast_rows += build_forecast_forcing(session, backend, slug, issue_dates)

    abt_rows = build_abt(session, slugs, abt_version)

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
