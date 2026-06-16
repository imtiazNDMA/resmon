"""SQLAlchemy models. Phase 0 lands the three frozen-contract tables and the minimal
``reservoir`` they reference; the full schema (ground truth, rating curve, predictions,
release-risk, pipeline runs) lands in Phase 1.
"""

from __future__ import annotations

from core.models.abt import AnalyticalBaseTable
from core.models.base import CONTRACT_VERSION, Base
from core.models.forecast_forcing import ForecastForcing
from core.models.observation import Observation
from core.models.reservoir import Reservoir

__all__ = [
    "Base",
    "CONTRACT_VERSION",
    "Reservoir",
    "Observation",
    "AnalyticalBaseTable",
    "ForecastForcing",
]
