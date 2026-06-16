"""Pooled Δ-fill forecaster (ADR-0006, FR-ML-2).

One model across all reservoirs, predicting **Δ`pct_filled`** over a horizon (not the
absolute level — that would just echo persistence), inflow-aware, direct multi-horizon
(horizon is a feature). Gradient-boosted to start (small-data, §8.5). Conformal split
intervals give finite-sample calibration. Trains on `pct_filled` from the storage series
(SAR-derived in production, ADR-0005); with synthetic forcing the inflow signal is weak,
so skill here is a machinery check.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

FEATURES = ["current_pct", "rate", "doy_sin", "doy_cos", "normal_pct", "horizon", "log_capacity"]
MAX_HORIZON = 14


def build_examples(df: pd.DataFrame) -> pd.DataFrame:
    """From a per-reservoir weekly fill series build (base, target) Δ-fill examples for
    every pair within MAX_HORIZON days. Columns: FEATURES + meta + ``delta`` target."""
    rows: list[dict] = []
    for rid, g in df.groupby("reservoir_id"):
        g = g.sort_values("date").reset_index(drop=True)
        pct = g["pct_filled"].to_numpy(dtype=float)
        normal = g["normal_storage_pct"].to_numpy(dtype=float)
        cap = float(g["live_capacity_bcm"].iloc[0])
        for i in range(len(g)):
            if i == 0:
                rate = 0.0
            else:
                dd = (g["date"].iloc[i] - g["date"].iloc[i - 1]).days
                rate = (pct[i] - pct[i - 1]) / dd if dd > 0 else 0.0
            doy = g["date"].iloc[i].timetuple().tm_yday
            norm_i = normal[i] if not np.isnan(normal[i]) else pct[i]
            for j in range(i + 1, len(g)):
                gap = (g["date"].iloc[j] - g["date"].iloc[i]).days
                if gap < 1:
                    continue
                if gap > MAX_HORIZON:
                    break
                norm_j = normal[j] if not np.isnan(normal[j]) else pct[i]
                rows.append(
                    {
                        "reservoir_id": rid,
                        "base_date": g["date"].iloc[i],
                        "target_date": g["date"].iloc[j],
                        "current_pct": pct[i],
                        "rate": rate,
                        "doy_sin": np.sin(2 * np.pi * doy / 365.0),
                        "doy_cos": np.cos(2 * np.pi * doy / 365.0),
                        "normal_pct": norm_i,
                        "horizon": gap,
                        "log_capacity": np.log(cap),
                        "normal_pct_target": norm_j,
                        "delta": pct[j] - pct[i],
                    }
                )
    return pd.DataFrame(rows)


@dataclass
class Forecaster:
    interval_quantile: float = 0.9
    model: object = field(default=None, repr=False)
    conformal_halfwidth: float = 0.0

    def fit(self, ex: pd.DataFrame) -> Forecaster:
        from sklearn.ensemble import HistGradientBoostingRegressor

        # Small-data regime (§8.5): regularize hard so the model shrinks toward "no
        # change" when there's no real inflow signal, rather than over-predicting deltas
        # (which loses to persistence at short horizons).
        self.model = HistGradientBoostingRegressor(
            max_depth=2,
            max_iter=80,
            learning_rate=0.03,
            min_samples_leaf=20,
            l2_regularization=1.0,
            random_state=0,
        ).fit(ex[FEATURES], ex["delta"])
        return self

    def predict_delta(self, ex: pd.DataFrame) -> np.ndarray:
        return self.model.predict(ex[FEATURES])  # type: ignore[attr-defined]

    def conformalize(self, ex_cal: pd.DataFrame) -> None:
        residuals = np.abs(ex_cal["delta"].to_numpy(dtype=float) - self.predict_delta(ex_cal))
        self.conformal_halfwidth = float(np.quantile(residuals, self.interval_quantile))

    def predict_with_interval(self, ex: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Returns (predicted_pct, interval_low, interval_high) at the target horizons."""
        delta = self.predict_delta(ex)
        pred_pct = ex["current_pct"].to_numpy(dtype=float) + delta
        return (
            pred_pct,
            pred_pct - self.conformal_halfwidth,
            pred_pct + self.conformal_halfwidth,
        )
