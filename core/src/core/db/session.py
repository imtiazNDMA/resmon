"""SQLAlchemy engine + session factories (read-write and read-only roles, NFR-SEC-3)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import get_settings


def make_engine(readonly: bool = False) -> Engine:
    """Build a new engine with an explicitly bounded pool (D4).

    Prefer :func:`get_engine` — one shared engine (and pool) per role per process.
    """
    settings = get_settings()
    url = settings.database_url_ro if readonly else settings.database_url_rw
    if not url:
        role = "DATABASE_URL_RO" if readonly else "DATABASE_URL_RW"
        raise RuntimeError(f"{role} must be set before opening a database connection")
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=30,
        future=True,
    )


@lru_cache(maxsize=2)
def get_engine(readonly: bool = False) -> Engine:
    """Cached per-role engine — callers share one pool instead of leaking engines (D3)."""
    return make_engine(readonly=readonly)


_rw_factory: sessionmaker[Session] | None = None
_ro_factory: sessionmaker[Session] | None = None


def _factory(readonly: bool) -> sessionmaker[Session]:
    global _rw_factory, _ro_factory
    if readonly:
        if _ro_factory is None:
            _ro_factory = sessionmaker(bind=get_engine(readonly=True), expire_on_commit=False)
        return _ro_factory
    if _rw_factory is None:
        _rw_factory = sessionmaker(bind=get_engine(readonly=False), expire_on_commit=False)
    return _rw_factory


@contextmanager
def session_scope(readonly: bool = False) -> Iterator[Session]:
    """Transactional session scope: commit on success, rollback on error."""
    session = _factory(readonly)()
    try:
        yield session
        if not readonly:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
