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


@pytest.fixture
def conn(engine):
    """A connection in a transaction rolled back after each test (no persisted data).

    Truncates the app tables at the start of the transaction so each test sees a clean
    slate even if the database already holds committed data (e.g. from the demo
    bootstrap). The TRUNCATE rolls back with everything else, leaving that data intact.
    """
    with engine.connect() as c:
        tx = c.begin()
        c.execute(text("TRUNCATE reservoir, model_version CASCADE"))
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
