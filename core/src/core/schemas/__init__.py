"""Pydantic v2 schemas mirroring the SQLAlchemy models. ``Read`` variants use
``from_attributes`` for ORM round-trips; ``Upsert`` variants are the pipeline write
contract. The three contract tables mirror ``docs/contracts/observation-and-abt.md``.
"""

from __future__ import annotations

from core.schemas.abt import AnalyticalBaseTableRow
from core.schemas.forecast_forcing import ForecastForcingRow
from core.schemas.observation import ObservationRead, ObservationUpsert

__all__ = [
    "ObservationRead",
    "ObservationUpsert",
    "AnalyticalBaseTableRow",
    "ForecastForcingRow",
]
