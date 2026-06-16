"""One-shot bootstrap: populate the database with the full pipeline and COMMIT, so the
API/dashboard have data to serve. Assumes migrations are already applied.

Run:  uv run python scripts/bootstrap.py
Uses the fixture data-access backend (no GEE needed). Idempotent — safe to re-run.
"""

from __future__ import annotations

import os

os.environ.setdefault("DATA_ACCESS_BACKEND", "fixture")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "2")

from core.db.session import make_engine  # noqa: E402
from orchestration.pipeline import run_full_pipeline  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402


def main() -> None:
    with Session(make_engine()) as session:
        summary = run_full_pipeline(session)
        session.commit()

    rr = summary["release_risk"]["assessments"]
    print("Bootstrap complete:")
    print(f"  reservoirs seeded : {summary['de']['reservoirs_seeded']}")
    print(
        f"  observations      : {summary['rs']['observations_written']} "
        f"({summary['rs']['extraction_method']})"
    )
    print(f"  AC-2 gate passed  : {summary['ground_truthing']['ac2_passed']}")
    print(f"  predictions       : {summary['forecasting']['predictions_written']}")
    for rid, a in rr.items():
        print(f"  release-risk      : {rid:14s} {a['risk_level']}")


if __name__ == "__main__":
    main()
