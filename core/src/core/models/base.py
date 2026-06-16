"""SQLAlchemy 2.x declarative base shared by every model.

The frozen-contract tables (``observation``, ``analytical_base_table``,
``forecast_forcing``) mirror ``docs/contracts/observation-and-abt.md`` 1:1; the
contract-parity test introspects this metadata against the markdown (ADR-0003).
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase

# The contract version this schema mirrors. Bumping a contract column requires
# bumping this and the markdown in lockstep (ADR-0003).
CONTRACT_VERSION = 3


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
