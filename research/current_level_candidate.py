"""Editable candidate for current reservoir level estimation.

Autoresearch agents may edit this file only. The evaluator imports ``fit`` and
``predict`` and scores predictions on a chronological holdout of matched
SAR-area/bulletin pairs.

Contract:
- fit(train_df) -> any model object
- predict(model, rows_df) -> DataFrame/dict with columns:
  - level_m
  - live_storage_bcm or pct_filled
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ReservoirCurve:
    storage_coeffs: list[float]
    level_coeffs: list[float]


@dataclass(frozen=True)
class CandidateModel:
    curves: dict[str, ReservoirCurve]
    fallback: ReservoirCurve


def _safe_degree(area: np.ndarray, degree: int) -> int:
    return min(degree, max(1, np.unique(area).size - 1))


def _fit_curve(frame: pd.DataFrame) -> ReservoirCurve:
    area = frame["area_km2"].to_numpy(dtype=float)
    storage = frame["live_storage_bcm"].to_numpy(dtype=float)
    level = frame["level_m"].to_numpy(dtype=float)
    return ReservoirCurve(
        storage_coeffs=[float(x) for x in np.polyfit(area, storage, _safe_degree(area, 1))],
        level_coeffs=[float(x) for x in np.polyfit(area, level, _safe_degree(area, 2))],
    )


def fit(train_df: pd.DataFrame) -> CandidateModel:
    curves = {
        str(reservoir_id): _fit_curve(group)
        for reservoir_id, group in train_df.groupby("reservoir_id")
    }
    return CandidateModel(curves=curves, fallback=_fit_curve(train_df))


def predict(model: CandidateModel, rows_df: pd.DataFrame) -> pd.DataFrame:
    storage: list[float] = []
    level: list[float] = []
    for row in rows_df.itertuples(index=False):
        curve = model.curves.get(str(row.reservoir_id), model.fallback)
        area = float(row.area_km2)
        storage.append(float(np.polyval(curve.storage_coeffs, area)))
        level.append(float(np.polyval(curve.level_coeffs, area)))
    return pd.DataFrame({"live_storage_bcm": storage, "level_m": level})
