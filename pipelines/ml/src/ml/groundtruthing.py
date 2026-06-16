"""Ground-truthing workflow (FR-GT-3..7) — the foundational AC-2 gate.

For each reservoir: read matched (extracted_area, bulletin) pairs, fit the empirical
rating curve on a time-ordered train split, evaluate held-out fill-% MAE (walk-forward),
persist the versioned `RatingCurve` (one active per reservoir), backfill `derived_*` +
residuals onto `observation`/`ground_truth_match` (Pass-2, §5.6), and apply the AC-2 gate.

NOTE: with synthetic SAR areas the held-out MAE is artificially low — this validates the
gate machinery + curve fit, not real extraction accuracy (which needs live GEE).
"""

from __future__ import annotations

import json

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from ml.curve import RatingCurveFit, fit_empirical
from ml.gate import ac2_gate, fill_pct_mae

MIN_PAIRS = 5
TRAIN_FRACTION = 0.8


def _read_pairs(conn, reservoir_id: str, extraction_method: str) -> pd.DataFrame:
    return pd.read_sql(
        text(
            """
            SELECT m.gt_date, m.acquisition_date, m.extraction_version, m.extracted_area,
                   g.pct_filled, g.live_storage_bcm, g.level_m, g.live_capacity_bcm
            FROM ground_truth_match m
            JOIN ground_truth g
              ON g.reservoir_id = m.reservoir_id AND g.date = m.gt_date
            WHERE m.reservoir_id = :r AND m.extraction_method = :em
              AND m.extracted_area IS NOT NULL AND g.pct_filled IS NOT NULL
              AND g.live_storage_bcm IS NOT NULL AND g.level_m IS NOT NULL
            ORDER BY m.gt_date
            """
        ),
        conn,
        params={"r": reservoir_id, "em": extraction_method},
        parse_dates=["gt_date", "acquisition_date"],
    )


def _persist_curve(
    session: Session, fit: RatingCurveFit, frl_m: float, mae: float, n_train: int, n_test: int
) -> None:
    session.execute(
        text("UPDATE rating_curve SET is_active = false WHERE reservoir_id = :r AND is_active"),
        {"r": fit.reservoir_id},
    )
    session.execute(
        text(
            """
            INSERT INTO rating_curve
              (reservoir_id, version, fit_type, area_to_storage_params, area_to_level_params,
               frl_anchor, observed_range, fit_metrics, valid_from, is_active)
            VALUES
              (:r, :v, 'empirical', CAST(:storage AS jsonb), CAST(:level AS jsonb),
               CAST(:anchor AS jsonb), CAST(:obs AS jsonb), CAST(:metrics AS jsonb),
               CURRENT_DATE, true)
            ON CONFLICT (reservoir_id, version) DO UPDATE SET
               area_to_storage_params = EXCLUDED.area_to_storage_params,
               fit_metrics = EXCLUDED.fit_metrics, is_active = true
            """
        ),
        {
            "r": fit.reservoir_id,
            "v": fit.version,
            "storage": json.dumps({"coeffs": fit.storage_coeffs}),
            "level": json.dumps({"coeffs": fit.level_coeffs}),
            "anchor": json.dumps({"frl_m": frl_m, "capacity_bcm": fit.capacity_bcm}),
            "obs": json.dumps(fit.observed_range),
            "metrics": json.dumps(
                {"fill_pct_mae_holdout": mae, "n_train": n_train, "n_test": n_test}
            ),
        },
    )


def _backfill(session: Session, fit: RatingCurveFit, df: pd.DataFrame) -> None:
    """Pass-2: write derived_* + residuals back to observation and ground_truth_match."""
    area = df["extracted_area"].to_numpy(dtype=float)
    derived_storage = fit.storage_for_area(area)
    derived_level = fit.level_for_area(area)
    derived_pct = derived_storage / fit.capacity_bcm * 100.0
    residual = derived_pct - df["pct_filled"].to_numpy(dtype=float)

    match_rows, obs_rows = [], []
    for i in range(len(df)):
        match_rows.append(
            {
                "r": fit.reservoir_id,
                "d": df["gt_date"].iloc[i].date(),
                "ev": df["extraction_version"].iloc[i],
                "vol": float(derived_storage[i]),
                "lvl": float(derived_level[i]),
                "pct": float(derived_pct[i]),
                "res": float(residual[i]),
                "ver": fit.version,
            }
        )
        obs_rows.append(
            {
                "r": fit.reservoir_id,
                "ad": df["acquisition_date"].iloc[i].date(),
                "vol": float(derived_storage[i]),
                "lvl": float(derived_level[i]),
            }
        )
    session.execute(
        text(
            "UPDATE ground_truth_match SET derived_volume=:vol, derived_level=:lvl, "
            "derived_pct_filled=:pct, residual_vs_ground_truth=:res, rating_curve_version=:ver "
            "WHERE reservoir_id=:r AND gt_date=:d AND extraction_version=:ev"
        ),
        match_rows,
    )
    session.execute(
        text(
            "UPDATE observation SET derived_volume=:vol, derived_level=:lvl "
            "WHERE reservoir_id=:r AND acquisition_date=:ad"
        ),
        obs_rows,
    )


def run_ground_truthing(
    session: Session,
    version: str = "rc_v1",
    extraction_method: str = "otsu_vh",
    tolerance: float = 10.0,
) -> dict:
    """Fit + gate the rating curve per reservoir. Returns maes, gate result, curve count."""
    conn = session.connection()
    reservoirs = conn.execute(text("SELECT reservoir_id, frl_m FROM reservoir")).all()

    maes: dict[str, float] = {}
    skipped: list[str] = []
    curves = 0
    for rid, frl_m in reservoirs:
        df = _read_pairs(conn, rid, extraction_method)
        if len(df) < MIN_PAIRS:
            skipped.append(rid)
            continue
        n_train = int(len(df) * TRAIN_FRACTION)
        train, test = df.iloc[:n_train], df.iloc[n_train:]
        cap = float(df["live_capacity_bcm"].iloc[0])
        fit = fit_empirical(
            rid,
            version,
            train["extracted_area"].to_numpy(),
            train["live_storage_bcm"].to_numpy(),
            train["level_m"].to_numpy(),
            cap,
        )
        derived_pct = fit.pct_filled_for_area(test["extracted_area"].to_numpy())
        mae = fill_pct_mae(derived_pct, test["pct_filled"].to_numpy())
        maes[rid] = mae
        _persist_curve(session, fit, float(frl_m), mae, len(train), len(test))
        _backfill(session, fit, df)
        curves += 1

    gate = ac2_gate(maes, tolerance)
    return {
        "per_reservoir_mae": maes,
        "skipped": skipped,
        "curves_persisted": curves,
        "ac2_passed": gate.passed,
        "ac2_worst_mae": gate.worst_mae,
        "ac2_tolerance": gate.tolerance_pct,
    }
