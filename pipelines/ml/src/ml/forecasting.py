"""Forecasting orchestrator (FR-ML-2/5, AC-4): train the pooled Δ-fill model, evaluate
skill vs persistence + climatology with **expanding-window walk-forward CV** (purged, no
example spanning a fold boundary), and persist `Prediction` rows (1–14 day, per-horizon
conformal intervals, daily horizons interpolated between weekly anchors per ADR-0006)
with model + abt provenance. Results are stamped with ``on_synthetic_data`` provenance
(C5): when the platform's Observation rows are synthetic/stub, every skill number here
is a machinery check, not evidence.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from ml.baselines import climatology_delta, persistence_delta
from ml.forecaster import FORCING_FEATURES, MAX_HORIZON, Forecaster, build_examples


def _read_series(conn, abt_version: str) -> pd.DataFrame:
    abt = pd.read_sql(
        text(
            """
            SELECT reservoir_id, date,
                   COALESCE(derived_volume / NULLIF(live_capacity_bcm, 0) * 100,
                            gt_pct_filled) AS pct_filled,
                   normal_storage_pct, live_capacity_bcm,
                   catchment_precip, antecedent_precip_index, snow_cover_area, swe,
                   degree_day_melt, evaporation
            FROM analytical_base_table
            WHERE abt_version = :abt AND row_quality <> 'quarantine'
            ORDER BY reservoir_id, date
            """
        ),
        conn,
        params={"abt": abt_version},
        parse_dates=["date"],
    )
    if not abt.empty and abt["pct_filled"].notna().sum() >= 30:
        return abt.dropna(subset=["pct_filled"]).reset_index(drop=True)
    # Fallback keeps historical tests and pre-closed-loop deployments runnable, but the
    # ABT/SAR path above is preferred whenever the estimation bridge has populated it.
    return pd.read_sql(
        text(
            "SELECT reservoir_id, date, pct_filled, normal_storage_pct, live_capacity_bcm "
            "FROM ground_truth WHERE row_quality <> 'quarantine' AND pct_filled IS NOT NULL "
            "ORDER BY reservoir_id, date"
        ),
        conn,
        parse_dates=["date"],
    )


def _observations_synthetic(conn) -> bool:
    """C5 provenance: True when any Observation row carries synthetic provenance —
    scene_ids containing 'synthetic'/'stub', or extraction_method = 'stub'. The bulletin
    ground truth itself is real; this flags that the SAR side of the closed loop
    (ADR-0005) is synthetic, so downstream gate/skill numbers are machinery checks."""
    n = conn.execute(
        text(
            "SELECT count(*) FROM observation "
            "WHERE 'synthetic' = ANY(scene_ids) OR 'stub' = ANY(scene_ids) "
            "OR extraction_method = 'stub'"
        )
    ).scalar_one()
    return bool(n)


def _latest_base_features(df: pd.DataFrame) -> list[dict]:
    """One base-feature dict per reservoir at its latest date (for trajectory serving)."""
    out: list[dict] = []
    for rid, g in df.groupby("reservoir_id"):
        g = g.sort_values("date").reset_index(drop=True)
        i = len(g) - 1
        pct = g["pct_filled"].to_numpy(dtype=float)
        normal = g["normal_storage_pct"].to_numpy(dtype=float)
        cap = float(g["live_capacity_bcm"].iloc[0])
        dd = (g["date"].iloc[i] - g["date"].iloc[i - 1]).days if i > 0 else 1
        rate = (pct[i] - pct[i - 1]) / dd if i > 0 and dd > 0 else 0.0
        doy = g["date"].iloc[i].timetuple().tm_yday
        norm_i = normal[i] if not np.isnan(normal[i]) else pct[i]
        out.append(
            {
                "reservoir_id": rid,
                "base_date": g["date"].iloc[i],
                "capacity_bcm": cap,
                "features": {
                    "current_pct": pct[i],
                    "rate": rate,
                    "doy_sin": np.sin(2 * np.pi * doy / 365.0),
                    "doy_cos": np.cos(2 * np.pi * doy / 365.0),
                    "normal_pct": norm_i,
                    "log_capacity": np.log(cap),
                    **{
                        name: (
                            float(g[name].iloc[i])
                            if name in g.columns and pd.notna(g[name].iloc[i])
                            else np.nan
                        )
                        for name in FORCING_FEATURES
                    },
                },
            }
        )
    return out


def _forecast_forcing(conn, reservoir_id: str, issue_date, horizons: list[int]) -> dict[int, dict]:
    rows = conn.execute(
        text(
            """
            SELECT horizon, forecast_precip, forecast_degree_day_melt
            FROM forecast_forcing
            WHERE reservoir_id = :r AND issue_date = :d AND horizon = ANY(:h)
            """
        ),
        {"r": reservoir_id, "d": issue_date.date(), "h": horizons},
    ).mappings()
    return {
        int(r["horizon"]): {
            "forecast_precip": r["forecast_precip"],
            "forecast_degree_day_melt": r["forecast_degree_day_melt"],
        }
        for r in rows
    }


def _active_curves(conn) -> dict[str, dict]:
    rows = conn.execute(
        text(
            """
            SELECT reservoir_id, area_to_storage_params, area_to_level_params, frl_anchor
            FROM rating_curve WHERE is_active
            """
        )
    ).mappings()
    return {str(r["reservoir_id"]): dict(r) for r in rows}


def _level_for_volume(curve: dict | None, volume_bcm: float) -> float | None:
    if curve is None:
        return None
    storage_coeffs = curve["area_to_storage_params"].get("coeffs", [])
    level_coeffs = curve["area_to_level_params"].get("coeffs", [])
    if len(storage_coeffs) != 2 or not level_coeffs:
        return None
    slope, intercept = float(storage_coeffs[0]), float(storage_coeffs[1])
    if abs(slope) < 1e-12:
        return None
    area = (volume_bcm - intercept) / slope
    return float(np.polyval([float(c) for c in level_coeffs], area))


def walk_forward_evaluate(
    ex: pd.DataFrame, n_folds: int = 4, min_train_frac: float = 0.4, cal_frac: float = 0.15
) -> dict:
    """Expanding-window walk-forward CV with a MAX_HORIZON purge/embargo (C4).

    Folds are contiguous windows of base dates after an initial ``min_train_frac``
    burn-in; training expands as the origin rolls forward. For each fold, the training
    pool is every example whose ``target_date`` falls strictly BEFORE the fold's first
    base date — because every example spans ≤ MAX_HORIZON days, this *is* the
    MAX_HORIZON-day purge: no train (or calibration) example's target crosses the
    boundary into the test window. Calibration is the trailing ``cal_frac`` of the
    pool's base dates, itself purged from the fit set the same way.

    Reports pooled, per-horizon and per-reservoir MAE for the model and the persistence
    / climatology baselines, skill (1 − model/baseline), and PICP of the nominal
    ``interval_quantile`` conformal interval.
    """
    base_dates = np.sort(ex["base_date"].unique())
    eval_dates = base_dates[int(len(base_dates) * min_train_frac) :]
    folds = [f for f in np.array_split(eval_dates, n_folds) if len(f)]
    frames: list[pd.DataFrame] = []
    folds_run = 0
    for fold in folds:
        w_start, w_end = fold[0], fold[-1]
        test = ex[(ex["base_date"] >= w_start) & (ex["base_date"] <= w_end)]
        pool = ex[ex["target_date"] < w_start]
        pool_dates = np.sort(pool["base_date"].unique())
        if len(pool_dates) < 10 or len(test) == 0:
            continue
        cal_start = pool_dates[int(len(pool_dates) * (1 - cal_frac))]
        fit_ex = pool[pool["target_date"] < cal_start]
        cal_ex = pool[pool["base_date"] >= cal_start]
        if len(fit_ex) < 30 or len(cal_ex) < 5:
            continue
        fc = Forecaster().fit(fit_ex)
        fc.conformalize(cal_ex)
        pred_pct, low, high = fc.predict_with_interval(test)
        actual_delta = test["delta"].to_numpy(dtype=float)
        actual_pct = test["current_pct"].to_numpy(dtype=float) + actual_delta
        clim = climatology_delta(
            test["current_pct"].to_numpy(), test["normal_pct_target"].to_numpy()
        )
        frames.append(
            pd.DataFrame(
                {
                    "reservoir_id": test["reservoir_id"].to_numpy(),
                    "horizon": test["horizon"].to_numpy(dtype=int),
                    "abs_err_model": np.abs(pred_pct - actual_pct),
                    "abs_err_persistence": np.abs(persistence_delta(len(test)) - actual_delta),
                    "abs_err_climatology": np.abs(clim - actual_delta),
                    "covered": (actual_pct >= low) & (actual_pct <= high),
                }
            )
        )
        folds_run += 1
    if not frames:
        return {"evaluated": False, "reason": "insufficient examples for walk-forward CV"}

    r = pd.concat(frames, ignore_index=True)

    def _mae_block(g: pd.DataFrame) -> dict:
        return {
            "model_mae": float(g["abs_err_model"].mean()),
            "persistence_mae": float(g["abs_err_persistence"].mean()),
            "climatology_mae": float(g["abs_err_climatology"].mean()),
            "n": int(len(g)),
        }

    model_mae = float(r["abs_err_model"].mean())
    persistence_mae = float(r["abs_err_persistence"].mean())
    climatology_mae = float(r["abs_err_climatology"].mean())
    return {
        "evaluated": True,
        "cv": (
            "expanding-window walk-forward, MAX_HORIZON purge "
            "(train target_date < test window start)"
        ),
        "n_folds_run": folds_run,
        "model_mae": model_mae,
        "persistence_mae": persistence_mae,
        "climatology_mae": climatology_mae,
        "skill_vs_persistence": (
            float(1.0 - model_mae / persistence_mae) if persistence_mae > 0 else None
        ),
        "skill_vs_climatology": (
            float(1.0 - model_mae / climatology_mae) if climatology_mae > 0 else None
        ),
        "picp_90": float(r["covered"].mean()),
        "per_horizon_mae": {str(h): _mae_block(g) for h, g in r.groupby("horizon")},
        "per_reservoir_mae": {str(rid): _mae_block(g) for rid, g in r.groupby("reservoir_id")},
        "n_test": int(len(r)),
    }


def run_forecasting(
    session: Session,
    abt_version: str = "abt_v1",
    version: str = "fc_v1",
    run_timestamp: datetime | None = None,
) -> dict:
    """Evaluate with purged expanding-window walk-forward CV, refit a serving model on
    the full (purged-calibration) history, persist model_version metrics + Predictions.
    Daily horizons 1..MAX_HORIZON are interpolated between the trained weekly anchor
    horizons (ADR-0006) — the tree model is never queried at a horizon it wasn't
    trained on."""
    run_ts = run_timestamp or datetime.now(UTC)
    conn = session.connection()
    df = _read_series(conn, abt_version)
    ex = build_examples(df).sort_values("base_date").reset_index(drop=True)
    if len(ex) < 30:
        return {"trained": False, "reason": "insufficient examples"}

    eval_metrics = walk_forward_evaluate(ex)
    if not eval_metrics.pop("evaluated"):
        return {"trained": False, "reason": eval_metrics.get("reason", "cv failed")}

    # Serving model: fit on everything except a trailing calibration window, purged the
    # same way (no fit example's target crosses into the calibration base dates).
    base_dates = np.sort(ex["base_date"].unique())
    cal_start = base_dates[int(len(base_dates) * 0.85)]
    fit_ex = ex[ex["target_date"] < cal_start]
    cal_ex = ex[ex["base_date"] >= cal_start]
    fc = Forecaster().fit(fit_ex)
    fc.conformalize(cal_ex)

    metrics = {
        **eval_metrics,
        "conformal_halfwidth": max(fc.conformal_halfwidths.values()),
        "conformal_halfwidth_by_horizon": {
            str(h): float(w) for h, w in fc.conformal_halfwidths.items()
        },
        "n_train": len(fit_ex),
        "on_synthetic_data": _observations_synthetic(conn),
    }
    model_version_id = conn.execute(
        text(
            "INSERT INTO model_version (model_name, version, model_stage, "
            "trained_on_abt_version, metrics) VALUES "
            "('forecaster', :v, 'staging', :abt, CAST(:m AS jsonb)) "
            "ON CONFLICT (model_name, version) DO UPDATE SET "
            "metrics = EXCLUDED.metrics, trained_on_abt_version = EXCLUDED.trained_on_abt_version "
            "RETURNING id"
        ),
        {"v": version, "abt": abt_version, "m": json.dumps(metrics)},
    ).scalar_one()

    horizons = list(range(1, MAX_HORIZON + 1))
    curves = _active_curves(conn)
    pred_rows: list[dict] = []
    for base in _latest_base_features(df):
        horizon_features = _forecast_forcing(
            conn, base["reservoir_id"], base["base_date"], horizons
        )
        pred_pct, low, high = fc.predict_fill_trajectory(
            base["features"], horizons, horizon_features
        )
        capacity = float(base["capacity_bcm"])
        curve = curves.get(base["reservoir_id"])
        for k, h in enumerate(horizons):
            volume = float(pred_pct[k]) / 100.0 * capacity
            pred_rows.append(
                {
                    "r": base["reservoir_id"],
                    "ts": run_ts,
                    "hd": (base["base_date"] + timedelta(days=h)).date(),
                    "pct": float(pred_pct[k]),
                    "vol": volume,
                    "lvl": _level_for_volume(curve, volume),
                    "lo": float(low[k]),
                    "hi": float(high[k]),
                    "mv": model_version_id,
                    "abt": abt_version,
                }
            )
    session.execute(
        text(
            "INSERT INTO prediction (reservoir_id, run_timestamp, horizon_date, "
            "predicted_level_m, predicted_volume_bcm, predicted_pct_filled, "
            "interval_low, interval_high, model_version_id, input_abt_version) "
            "VALUES (:r, :ts, :hd, :lvl, :vol, :pct, :lo, :hi, :mv, :abt)"
        ),
        pred_rows,
    )

    return {
        "trained": True,
        **metrics,
        "beats_persistence": metrics["model_mae"] < metrics["persistence_mae"],
        "predictions_written": len(pred_rows),
        "model_version": version,
    }
