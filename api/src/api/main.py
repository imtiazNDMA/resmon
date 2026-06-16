"""FastAPI app — Phase 0 seeds health/readiness only; domain routes land in Phase 7."""

from __future__ import annotations

from core.config import get_settings
from core.db.session import make_engine
from fastapi import FastAPI
from sqlalchemy import text

app = FastAPI(title="Reservoir Monitoring & Analytics API", version="0.1.0")


@app.get("/health")
def health() -> dict:
    """Liveness."""
    return {"status": "ok"}


@app.get("/health/ready")
def ready() -> dict:
    """Readiness: dependency reachability (DB now; MLflow/freshness as phases land)."""
    checks: dict[str, str] = {}
    try:
        with make_engine(readonly=True).connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - exercised in integration
        checks["database"] = f"error: {exc.__class__.__name__}"
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {
        "status": status,
        "checks": checks,
        "staleness_threshold_days": get_settings().data_staleness_threshold_days,
    }
