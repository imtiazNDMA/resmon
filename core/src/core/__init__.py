"""Shared core: configuration, SQLAlchemy models, Pydantic schemas, logging.

The single source of truth for the persisted data model. The SQLAlchemy models
for ``Observation``, ``AnalyticalBaseTable`` and ``ForecastForcing`` mirror the
frozen contract (``docs/contracts/observation-and-abt.md``) 1:1; CI enforces
parity (ADR-0003).
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
