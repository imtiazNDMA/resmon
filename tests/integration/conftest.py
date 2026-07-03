"""Integration fixtures. Skips the whole module if no migrated database is reachable
(unit-only runs stay green); CI provisions PostGIS + runs `alembic upgrade head` first.
"""

from __future__ import annotations

import pytest
from core.db.session import make_engine
from sqlalchemy import text
from sqlalchemy.orm import Session


@pytest.fixture(scope="session")
def engine():
    try:
        eng = make_engine()
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database not available: {exc.__class__.__name__}")
    return eng


# Children before parents (FK dependency order). prediction/release_risk are append-only
# (UPDATE/DELETE row triggers + BEFORE TRUNCATE statement triggers), so the cleanup
# briefly disables their user triggers inside the rolled-back transaction.
_CLEAN_TABLES = (
    "ground_truth_match",
    "prediction",
    "release_risk",
    "observation",
    "analytical_base_table",
    "forecast_forcing",
    "catchment_forcing",
    "ground_truth",
    "rating_curve",
    "reservoir_capacity_history",
    "pipeline_run",
    "model_version",
    "reservoir",
)


@pytest.fixture
def conn(engine):
    """A connection in a transaction rolled back after each test (no persisted data).

    Clears the app tables at the start of the transaction so each test sees a clean
    slate even if the database already holds committed data (e.g. from the demo
    bootstrap). DELETE (not TRUNCATE — forbidden on the append-only tables since
    migration 7c4e9a1d2b6f) rolls back with everything else, leaving that data intact.
    """
    with engine.connect() as c:
        tx = c.begin()
        c.execute(text("ALTER TABLE prediction DISABLE TRIGGER USER"))
        c.execute(text("ALTER TABLE release_risk DISABLE TRIGGER USER"))
        for table in _CLEAN_TABLES:
            c.execute(text(f"DELETE FROM {table}"))
        c.execute(text("ALTER TABLE prediction ENABLE TRIGGER USER"))
        c.execute(text("ALTER TABLE release_risk ENABLE TRIGGER USER"))
        try:
            yield c
        finally:
            tx.rollback()


@pytest.fixture
def session(conn):
    """An ORM Session bound to the rolled-back test connection."""
    s = Session(bind=conn)
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def add_reservoir(conn):
    """Factory: insert a minimal valid reservoir on the test connection, return its id."""

    def _add(rid: str = "test_res") -> str:
        conn.execute(
            text(
                """
                INSERT INTO reservoir
                  (reservoir_id, name, basin, dam_point, frl_m, live_capacity_bcm,
                   aoi_geom, aoi_version, orbit_relative, pass_direction, release_thresholds)
                VALUES
                  (:rid, :rid, 'Sutlej', ST_GeomFromText('POINT(76 31)', 4326), 500, 6.0,
                   ST_GeomFromText(
                     'MULTIPOLYGON(((76 31,76.1 31,76.1 31.1,76 31.1,76 31)))', 4326),
                   'v1', 12, 'ASC', '{}'::jsonb)
                """
            ),
            {"rid": rid},
        )
        return rid

    return _add
