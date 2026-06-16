"""SQLAlchemy engine + session factories (read-write and read-only roles, NFR-SEC-3)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import get_settings


def make_engine(readonly: bool = False) -> Engine:
    settings = get_settings()
    url = settings.database_url_ro if readonly else settings.database_url_rw
    return create_engine(url, pool_pre_ping=True, future=True)


_rw_factory: sessionmaker[Session] | None = None
_ro_factory: sessionmaker[Session] | None = None


def _factory(readonly: bool) -> sessionmaker[Session]:
    global _rw_factory, _ro_factory
    if readonly:
        if _ro_factory is None:
            _ro_factory = sessionmaker(bind=make_engine(readonly=True), expire_on_commit=False)
        return _ro_factory
    if _rw_factory is None:
        _rw_factory = sessionmaker(bind=make_engine(readonly=False), expire_on_commit=False)
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
