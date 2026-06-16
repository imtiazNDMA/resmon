"""End-to-end pipeline chain (AC-1): RS → DE → ML → serve, as plain Python.

In production a Prefect deployment schedules this and wires the RS→DE→ML trigger chain on
a worker (§4.3); the logic lives here so it runs with or without a Prefect runtime — which
is what the local bootstrap uses. Idempotent: every stage upserts, so re-running is safe.
"""

from __future__ import annotations

from data_engineering.fusion import fuse_observations_groundtruth
from data_engineering.pipeline import run_de_pipeline
from ml.forecasting import run_forecasting
from ml.groundtruthing import run_ground_truthing
from ml.release import run_release_risk
from remote_sensing.pipeline import run_rs_pipeline
from sqlalchemy.orm import Session


def run_full_pipeline(session: Session) -> dict:
    """Run the whole chain once against an open session (caller commits). Returns a
    per-stage summary."""
    de = run_de_pipeline(session)  # seed, bulletins → ground_truth, stub obs, fuse, forcing, ABT
    rs = run_rs_pipeline(session)  # real Observations replace the stubs
    fuse_observations_groundtruth(session)  # re-fuse on real extracted areas
    gt = run_ground_truthing(session)  # blended-empirical rating curve + AC-2 gate
    fc = run_forecasting(session)  # pooled Δ-fill forecast + Predictions
    rr = run_release_risk(session)  # release-risk over the forecast
    return {
        "de": de,
        "rs": rs,
        "ground_truthing": gt,
        "forecasting": fc,
        "release_risk": rr,
    }
