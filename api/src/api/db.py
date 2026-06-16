"""FastAPI DB dependency. Yields a read-only session; tests override this to bind to the
rolled-back test connection so they see uncommitted pipeline output.
"""

from __future__ import annotations

from collections.abc import Iterator

from core.db.session import session_scope
from sqlalchemy.orm import Session


def get_db() -> Iterator[Session]:
    with session_scope(readonly=True) as session:
        yield session
