"""End-to-end pipeline chain (AC-1): DE ingest → RS → fusion → ABT → ML → serve.

In production a Prefect deployment schedules this and wires the RS→DE→ML trigger chain
on a worker (§4.3); the logic lives here so it runs with or without a Prefect runtime —
which is what the local bootstrap uses. Idempotent: every stage upserts, so re-running
is safe.

Ordering matters (A2): the ABT is built only *after* the RS pipeline has written real
observations and fusion has matched them, so the gold table always contains this run's
extractions — never just the stubs the DE spine bootstrapped with.

Each stage writes a ``pipeline_run`` row (NFR-REL-2): stage name + row counts in
``row_counts``, status, started/finished timestamps, and the error text on failure.
Rows share the caller's transaction (single-session/single-commit), so a failed run's
rows persist only if the caller commits what the DB accepted before the failure.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from data_engineering.fusion import fuse_observations_groundtruth
from data_engineering.pipeline import build_and_validate_abt, run_de_pipeline
from data_engineering.reservoirs import REGISTRY
from ml.forecasting import run_forecasting
from ml.groundtruthing import run_ground_truthing
from ml.release import run_release_risk
from remote_sensing.pipeline import run_rs_pipeline
from sqlalchemy import text
from sqlalchemy.orm import Session

_PIPELINE_RUN_INSERT = text(
    """
    INSERT INTO pipeline_run
      (pipeline, status, started_at, finished_at, row_counts, error, triggered_by)
    VALUES
      (:pipeline, :status, :started_at, :finished_at, CAST(:row_counts AS jsonb),
       CAST(:error AS jsonb), :triggered_by)
    """
)


def _record_stage(session: Session, pipeline: str, stage: str, fn: Callable[[], Any]) -> Any:
    """Run one stage, writing its ``pipeline_run`` row (success or failure)."""
    started = datetime.now(UTC)
    try:
        result = fn()
    except Exception as exc:
        try:
            session.execute(
                _PIPELINE_RUN_INSERT,
                {
                    "pipeline": pipeline,
                    "status": "failed",
                    "started_at": started,
                    "finished_at": datetime.now(UTC),
                    "row_counts": json.dumps({"stage": stage}),
                    "error": json.dumps({"stage": stage, "error": str(exc)}, default=str),
                    "triggered_by": "run_full_pipeline",
                },
            )
        except Exception:
            # A DB failure leaves the transaction aborted, so this bookkeeping insert
            # can itself fail (and would roll back with the transaction anyway) —
            # surface the original stage error, not the bookkeeping one.
            pass
        raise
    row_counts = result if isinstance(result, dict) else {"rows": result}
    session.execute(
        _PIPELINE_RUN_INSERT,
        {
            "pipeline": pipeline,
            "status": "success",
            "started_at": started,
            "finished_at": datetime.now(UTC),
            "row_counts": json.dumps({"stage": stage, **row_counts}, default=str),
            "error": None,
            "triggered_by": "run_full_pipeline",
        },
    )
    return result


def run_full_pipeline(session: Session, abt_version: str = "abt_v1") -> dict:
    """Run the whole chain once against an open session (caller commits). Returns a
    per-stage summary."""
    slugs = [m.slug for m in REGISTRY.values()]

    # DE spine WITHOUT the ABT build: seed, bulletins → ground_truth, stub obs, forcing.
    de = _record_stage(
        session,
        "data_engineering",
        "de_spine",
        lambda: run_de_pipeline(session, abt_version=abt_version, build_abt_stage=False),
    )
    # Real Observations replace the stubs.
    rs = _record_stage(session, "remote_sensing", "rs_extract", lambda: run_rs_pipeline(session))
    # Re-fuse on the real extracted areas (stubs are excluded from matching).
    fused = _record_stage(
        session,
        "data_engineering",
        "fusion",
        lambda: fuse_observations_groundtruth(session),
    )
    gt = _record_stage(session, "ml", "ground_truthing", lambda: run_ground_truthing(session))
    # Gold ABT built AFTER rating-curve backfill so it carries SAR-derived storage/level.
    abt_rows = _record_stage(
        session,
        "data_engineering",
        "build_abt",
        lambda: build_and_validate_abt(session, slugs, abt_version),
    )
    fc = _record_stage(session, "ml", "forecasting", lambda: run_forecasting(session))
    rr = _record_stage(session, "ml", "release_risk", lambda: run_release_risk(session))
    return {
        "de": de,
        "rs": rs,
        "fusion_matches": fused,
        "abt_rows": abt_rows,
        "abt_version": abt_version,
        "ground_truthing": gt,
        "forecasting": fc,
        "release_risk": rr,
    }
