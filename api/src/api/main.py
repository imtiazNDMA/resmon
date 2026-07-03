"""FastAPI app — Phase 0 seeds health/readiness only; domain routes land in Phase 7."""

from __future__ import annotations

from core.config import get_settings
from core.db.session import get_engine
from fastapi import FastAPI
from sqlalchemy import text

from api.routes import router
from api.schemas import HealthResponse, ReadinessResponse

# root_path matches the deployed topology: Caddy's `handle_path /api/*` strips the
# prefix before proxying (and the Vite dev proxy does the same), so the app itself
# serves bare paths. Set API_ROOT_PATH="" for bare local uvicorn without a proxy.
app = FastAPI(
    title="Reservoir Monitoring & Analytics API",
    version="0.1.0",
    root_path=get_settings().api_root_path,
)
app.include_router(router)


@app.get("/health", response_model=HealthResponse)
def health() -> dict:
    """Liveness."""
    return {"status": "ok"}


@app.get("/health/ready", response_model=ReadinessResponse)
def ready() -> dict:
    """Readiness: dependency reachability (DB now; MLflow/freshness as phases land)."""
    checks: dict[str, str] = {}
    try:
        # Cached engine (D3): probing must not build a new engine+pool per request.
        with get_engine(readonly=True).connect() as conn:
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
