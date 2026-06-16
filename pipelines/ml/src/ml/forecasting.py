"""Forecasting orchestrator (FR-ML-2/5, AC-4): train the pooled Δ-fill model, evaluate
skill vs persistence + climatology on a walk-forward holdout, and persist `Prediction`
rows (1–14 day, conformal intervals) with model + abt provenance.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from ml.baselines import climatology_delta, mae, persistence_delta
from ml.forecaster import MAX_HORIZON, Forecaster, build_examples


def _read_series(conn) -> pd.DataFrame:
    return pd.read_sql(
        text(
            "SELECT reservoir_id, date, pct_filled, normal_storage_pct, live_capacity_bcm "
            "FROM ground_truth WHERE row_quality <> 'quarantine' AND pct_filled IS NOT NULL "
            "ORDER BY reservoir_id, date"
        ),
        conn,
        parse_dates=["date"],
    )


def _latest_base_rows(df: pd.DataFrame) -> pd.DataFrame:
    """One feature row per reservoir at its latest date, for horizons 1..MAX_HORIZON."""
    rows: list[dict] = []
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
        base = g["date"].iloc[i]
        for h in range(1, MAX_HORIZON + 1):
            rows.append(
                {
                    "reservoir_id": rid,
                    "base_date": base,
                    "target_date": base + timedelta(days=h),
                    "current_pct": pct[i],
                    "rate": rate,
                    "doy_sin": np.sin(2 * np.pi * doy / 365.0),
                    "doy_cos": np.cos(2 * np.pi * doy / 365.0),
                    "normal_pct": norm_i,
                    "horizon": h,
                    "log_capacity": np.log(cap),
                }
            )
    return pd.DataFrame(rows)


def run_forecasting(
    session: Session,
    abt_version: str = "abt_v1",
    version: str = "fc_v1",
    run_timestamp: datetime | None = None,
) -> dict:
    run_ts = run_timestamp or datetime.now(UTC)
    conn = session.connection()
    df = _read_series(conn)
    ex = build_examples(df).sort_values("base_date").reset_index(drop=True)
    if len(ex) < 30:
        return {"trained": False, "reason": "insufficient examples"}

    n = len(ex)
    train, cal, test = (
        ex.iloc[: int(n * 0.7)],
        ex.iloc[int(n * 0.7) : int(n * 0.85)],
        ex.iloc[int(n * 0.85) :],
    )
    fc = Forecaster().fit(train)
    fc.conformalize(cal)

    test_actual = test["delta"].to_numpy(dtype=float)
    model_mae = mae(fc.predict_delta(test), test_actual)
    persistence_mae = mae(persistence_delta(len(test)), test_actual)
    climatology_mae = mae(
        climatology_delta(test["current_pct"].to_numpy(), test["normal_pct_target"].to_numpy()),
        test_actual,
    )
    beats_persistence = model_mae < persistence_mae

    metrics = {
        "model_mae": model_mae,
        "persistence_mae": persistence_mae,
        "climatology_mae": climatology_mae,
        "conformal_halfwidth": fc.conformal_halfwidth,
        "n_train": len(train),
        "n_test": len(test),
    }
    model_version_id = conn.execute(
        text(
            "INSERT INTO model_version (model_name, version, model_stage, "
            "trained_on_abt_version, metrics) VALUES "
            "('forecaster', :v, 'staging', :abt, CAST(:m AS jsonb)) RETURNING id"
        ),
        {"v": version, "abt": abt_version, "m": json.dumps(metrics)},
    ).scalar_one()

    fr = _latest_base_rows(df)
    pred_pct, low, high = fc.predict_with_interval(fr)
    pred_rows = [
        {
            "r": fr["reservoir_id"].iloc[k],
            "ts": run_ts,
            "hd": fr["target_date"].iloc[k].date(),
            "pct": float(pred_pct[k]),
            "lo": float(low[k]),
            "hi": float(high[k]),
            "mv": model_version_id,
            "abt": abt_version,
        }
        for k in range(len(fr))
    ]
    session.execute(
        text(
            "INSERT INTO prediction (reservoir_id, run_timestamp, horizon_date, "
            "predicted_pct_filled, interval_low, interval_high, model_version_id, "
            "input_abt_version) VALUES (:r, :ts, :hd, :pct, :lo, :hi, :mv, :abt)"
        ),
        pred_rows,
    )

    return {
        "trained": True,
        **metrics,
        "beats_persistence": beats_persistence,
        "predictions_written": len(pred_rows),
        "model_version": version,
    }
