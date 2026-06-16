"""Settings load + API liveness (DB-free unit checks)."""

from __future__ import annotations

from api.main import health
from core.config import Settings, get_settings


def test_settings_defaults_load():
    s = Settings()
    assert s.app_env in {"dev", "prod"}
    assert s.data_staleness_threshold_days == 14  # D8
    assert s.data_access_backend in {"gee", "fixture", "openeo", "planetary"}


def test_get_settings_is_cached():
    assert get_settings() is get_settings()


def test_health_liveness():
    assert health() == {"status": "ok"}
