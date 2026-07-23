"""Autoresearch harness for the current-state estimation bridge.

This adapts Karpathy's ``autoresearch`` pattern to this domain: keep one editable
candidate file, run a fixed evaluator, and compare one lower-is-better score. The
target is current imagery estimation, not future forecasting:

    SAR extracted_area -> level_m / live_storage_bcm / pct_filled
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from importlib import util
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text


class CandidateError(RuntimeError):
    """Candidate module does not satisfy the small autoresearch contract."""


@dataclass(frozen=True)
class EvaluationConfig:
    train_fraction: float = 0.8
    min_pairs: int = 8
    include_synthetic: bool = False


def load_candidate(path: Path) -> ModuleType:
    spec = util.spec_from_file_location("current_level_candidate", path)
    if spec is None or spec.loader is None:
        raise CandidateError(f"could not import candidate from {path}")
    module = util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    for name in ("fit", "predict"):
        if not callable(getattr(module, name, None)):
            raise CandidateError(f"candidate must define callable {name}(...)")
    return module


def read_pairs(conn, *, include_synthetic: bool = False) -> pd.DataFrame:
    synthetic_filter = "" if include_synthetic else """
      AND NOT ('synthetic' = ANY(m.scene_ids) OR 'stub' = ANY(m.scene_ids))
      AND m.extraction_method <> 'stub'
    """
    return pd.read_sql(
        text(
            f"""
            SELECT m.reservoir_id,
                   m.gt_date,
                   m.acquisition_date,
                   m.extracted_area AS area_km2,
                   g.level_m,
                   g.live_storage_bcm,
                   g.pct_filled,
                   g.live_capacity_bcm,
                   m.area_confidence,
                   m.extraction_method,
                   m.scene_ids
            FROM ground_truth_match m
            JOIN ground_truth g
              ON g.reservoir_id = m.reservoir_id AND g.date = m.gt_date
            WHERE m.extracted_area IS NOT NULL
              AND g.level_m IS NOT NULL
              AND g.live_storage_bcm IS NOT NULL
              AND g.pct_filled IS NOT NULL
              {synthetic_filter}
            ORDER BY m.reservoir_id, m.gt_date
            """
        ),
        conn,
        parse_dates=["gt_date", "acquisition_date"],
    )


def chronological_holdout(
    pairs: pd.DataFrame, config: EvaluationConfig
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    train_parts: list[pd.DataFrame] = []
    test_parts: list[pd.DataFrame] = []
    skipped: list[str] = []
    for reservoir_id, group in pairs.groupby("reservoir_id"):
        group = group.sort_values("gt_date").reset_index(drop=True)
        if len(group) < config.min_pairs:
            skipped.append(str(reservoir_id))
            continue
        split = int(len(group) * config.train_fraction)
        split = min(max(split, 1), len(group) - 1)
        train_parts.append(group.iloc[:split].copy())
        test_parts.append(group.iloc[split:].copy())
    if not train_parts or not test_parts:
        raise CandidateError("not enough matched pairs for any reservoir")
    return (
        pd.concat(train_parts, ignore_index=True),
        pd.concat(test_parts, ignore_index=True),
        skipped,
    )


def _coerce_predictions(pred: Any, test: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(pred).reset_index(drop=True)
    if len(out) != len(test):
        raise CandidateError(f"candidate returned {len(out)} rows for {len(test)} test rows")
    if "live_storage_bcm" not in out.columns and "pct_filled" not in out.columns:
        raise CandidateError("candidate must predict live_storage_bcm or pct_filled")
    if "live_storage_bcm" not in out.columns:
        out["live_storage_bcm"] = out["pct_filled"] / 100.0 * test["live_capacity_bcm"].to_numpy()
    if "pct_filled" not in out.columns:
        out["pct_filled"] = out["live_storage_bcm"] / test["live_capacity_bcm"].to_numpy() * 100.0
    if "level_m" not in out.columns:
        raise CandidateError("candidate must predict level_m")
    for col in ("live_storage_bcm", "level_m", "pct_filled"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
        if not np.isfinite(out[col].to_numpy(dtype=float)).all():
            raise CandidateError(f"candidate produced non-finite {col}")
    return out


def evaluate_candidate(module: ModuleType, pairs: pd.DataFrame, config: EvaluationConfig) -> dict:
    train, test, skipped = chronological_holdout(pairs, config)
    model = module.fit(train.copy())
    pred = _coerce_predictions(module.predict(model, test.copy()), test)

    errors = pd.DataFrame(
        {
            "reservoir_id": test["reservoir_id"].to_numpy(),
            "abs_level_err_m": np.abs(pred["level_m"].to_numpy() - test["level_m"].to_numpy()),
            "abs_storage_err_bcm": np.abs(
                pred["live_storage_bcm"].to_numpy() - test["live_storage_bcm"].to_numpy()
            ),
            "abs_fill_err_pct": np.abs(
                pred["pct_filled"].to_numpy() - test["pct_filled"].to_numpy()
            ),
        }
    )

    def block(frame: pd.DataFrame) -> dict:
        return {
            "level_mae_m": float(frame["abs_level_err_m"].mean()),
            "storage_mae_bcm": float(frame["abs_storage_err_bcm"].mean()),
            "fill_mae_pct": float(frame["abs_fill_err_pct"].mean()),
            "n": int(len(frame)),
        }

    overall = block(errors)
    return {
        "score": overall["level_mae_m"],
        "score_name": "level_mae_m",
        "lower_is_better": True,
        "overall": overall,
        "per_reservoir": {
            str(reservoir_id): block(group)
            for reservoir_id, group in errors.groupby("reservoir_id")
        },
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "skipped_reservoirs": skipped,
        "include_synthetic": config.include_synthetic,
    }
