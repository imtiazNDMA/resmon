"""Alembic environment. Targets ``core.models.Base.metadata``; URL from env/settings."""

from __future__ import annotations

import os

from alembic import context
from core.config import get_settings
from core.models import Base
from sqlalchemy import create_engine, pool

target_metadata = Base.metadata

# PostGIS creates system tables (spatial_ref_sys) + schemas (tiger, topology) that are
# NOT part of our metadata. Without this, autogenerate tries to DROP them.
_POSTGIS_TABLES = {"spatial_ref_sys"}
_POSTGIS_SCHEMAS = {"tiger", "tiger_data", "topology"}


def include_object(obj, name, type_, reflected, compare_to):  # noqa: ANN001
    if type_ == "table" and name in _POSTGIS_TABLES:
        return False
    schema = getattr(obj, "schema", None)
    if schema in _POSTGIS_SCHEMAS:
        return False
    return True


def _url() -> str:
    return os.environ.get("DATABASE_URL_RW") or get_settings().database_url_rw


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_object=include_object,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool, future=True)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
