"""Typed application settings (pydantic-settings) reading the env contract (plan 01 §6.2).

Secrets are file-mounted where possible (NFR-SEC-2): the GEE key and JWT secret are
*paths*, never inline values.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- App / observability ---
    app_env: str = Field(default="dev")  # dev | prod
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="json")
    data_staleness_threshold_days: int = Field(default=14)  # NFR-REL-6 (D8)
    # Path prefix the reverse proxy strips before the app sees requests (Caddy
    # handle_path /api/*). Set empty ("") for bare local uvicorn without a proxy.
    api_root_path: str = Field(default="/api")

    # --- Database ---
    database_url_rw: str = Field(default="")
    database_url_ro: str = Field(default="")

    # --- MLflow / Prefect ---
    mlflow_tracking_uri: str = Field(default="http://localhost:5000")
    prefect_api_url: str = Field(default="http://localhost:4200/api")

    # --- Data access (the swappable GEE seam, §4.4) ---
    data_access_backend: str = Field(default="gee")  # gee | fixture | openeo | planetary
    gee_project: str | None = Field(default=None)
    gee_sa_key_file: str | None = Field(default=None)  # file-mounted, never inlined


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
