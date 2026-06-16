"""SQLAlchemy models — the full physical schema (Phase 1). Auth/alert tables are
intentionally descoped for v1 (see todos.md).
"""

from __future__ import annotations

from core.models.abt import AnalyticalBaseTable
from core.models.base import CONTRACT_VERSION, Base
from core.models.capacity_history import ReservoirCapacityHistory
from core.models.catchment_forcing import CatchmentForcing
from core.models.forecast_forcing import ForecastForcing
from core.models.ground_truth import GroundTruth
from core.models.ground_truth_match import GroundTruthMatch
from core.models.model_version import ModelVersion
from core.models.observation import Observation
from core.models.pipeline_run import PipelineRun
from core.models.prediction import Prediction
from core.models.rating_curve import RatingCurve
from core.models.release_risk import ReleaseRisk
from core.models.reservoir import Reservoir

__all__ = [
    "Base",
    "CONTRACT_VERSION",
    "Reservoir",
    "ReservoirCapacityHistory",
    "Observation",
    "GroundTruth",
    "GroundTruthMatch",
    "RatingCurve",
    "CatchmentForcing",
    "ForecastForcing",
    "AnalyticalBaseTable",
    "ModelVersion",
    "Prediction",
    "ReleaseRisk",
    "PipelineRun",
]
