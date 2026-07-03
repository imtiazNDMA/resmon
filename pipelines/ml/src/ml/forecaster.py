"""Pooled Δ-fill forecaster (ADR-0006, FR-ML-2).

One model across all reservoirs, predicting **Δ`pct_filled`** over a horizon (not the
absolute level — that would just echo persistence), inflow-aware, direct multi-horizon
(horizon is a feature). Gradient-boosted to start (small-data, §8.5). Split-conformal
intervals give finite-sample calibration, computed **per horizon** (weekly bulletins →
only ~7/14-day gaps carry calibration mass; other horizons are interpolated, see
``conformalize``). Because the training grid is weekly, arbitrary daily horizons are
served by interpolating between trained anchor horizons (``predict_fill_trajectory``,
per ADR-0006: "weekly resolution interpolated to daily with intervals that widen").
Trains on `pct_filled` from the storage series (SAR-derived in production, ADR-0005);
with synthetic forcing the inflow signal is weak, so skill here is a machinery check.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

FEATURES = ["current_pct", "rate", "doy_sin", "doy_cos", "normal_pct", "horizon", "log_capacity"]
MAX_HORIZON = 14
# Below this many calibration residuals a horizon falls back to the pooled halfwidth.
_MIN_CAL_PER_HORIZON = 5


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


def finite_sample_quantile(abs_residuals: np.ndarray, coverage: float) -> float:
    """Split-conformal finite-sample quantile of absolute calibration residuals: the
    ``ceil((n+1)*coverage)/n`` empirical quantile taken as an order statistic
    (``method='higher'``), which guarantees ≥ ``coverage`` marginal coverage under
    exchangeability (Vovk; Lei et al. 2018). Returns the max residual when n is too
    small for the adjusted level to be attainable."""
    r = np.asarray(abs_residuals, dtype=float)
    n = int(r.size)
    if n == 0:
        raise ValueError("no calibration residuals")
    q = math.ceil((n + 1) * coverage) / n
    if q >= 1.0:
        return float(r.max())
    return float(np.quantile(r, q, method="higher"))


@dataclass
class Forecaster:
    interval_quantile: float = 0.9
    model: object = field(default=None, repr=False)
    # Pooled (all-horizon) halfwidth — the fallback for thin per-horizon groups.
    conformal_halfwidth: float = 0.0
    # Per-horizon halfwidths keyed by the calibration horizons actually observed.
    conformal_halfwidths: dict[int, float] = field(default_factory=dict)
    trained_horizons: list[int] = field(default_factory=list)

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
        self.trained_horizons = sorted(int(h) for h in ex["horizon"].unique())
        return self

    def predict_delta(self, ex: pd.DataFrame) -> np.ndarray:
        return self.model.predict(ex[FEATURES])  # type: ignore[attr-defined]

    def conformalize(self, ex_cal: pd.DataFrame) -> None:
        """Split-conformal calibration with PER-HORIZON halfwidths.

        Residuals are grouped by the calibration horizons actually present (weekly
        bulletins → mostly 6–8 and 13–14 days); each group gets the finite-sample
        ``ceil((n+1)(1-α))/n`` quantile. Groups with < _MIN_CAL_PER_HORIZON residuals
        fall back to the pooled halfwidth. Widths are then forced monotone
        non-decreasing in horizon (uncertainty cannot shrink further out), and horizons
        between/below the calibrated anchors are served by linear interpolation from
        width 0 at h=0 (the current state is observed) — see ``_halfwidths_for``.
        """
        residuals = np.abs(ex_cal["delta"].to_numpy(dtype=float) - self.predict_delta(ex_cal))
        self.conformal_halfwidth = finite_sample_quantile(residuals, self.interval_quantile)
        horizons = ex_cal["horizon"].to_numpy(dtype=int)
        widths: dict[int, float] = {}
        for h in sorted(set(horizons.tolist())):
            r_h = residuals[horizons == h]
            widths[h] = (
                finite_sample_quantile(r_h, self.interval_quantile)
                if r_h.size >= _MIN_CAL_PER_HORIZON
                else self.conformal_halfwidth
            )
        prev = 0.0
        for h in sorted(widths):
            widths[h] = max(widths[h], prev)
            prev = widths[h]
        self.conformal_halfwidths = widths

    def _halfwidths_for(self, horizons: np.ndarray) -> np.ndarray:
        """Interval halfwidth per served horizon: linear interpolation between the
        anchor (0, 0) and the calibrated per-horizon widths; clamped flat at the widest
        anchor beyond the last calibrated horizon. Monotone non-decreasing by
        construction (documented interpolation/extrapolation for horizons the weekly
        calibration grid never observed)."""
        h = np.asarray(horizons, dtype=float)
        if not self.conformal_halfwidths:
            return np.full(h.shape, self.conformal_halfwidth)
        anchors = sorted(self.conformal_halfwidths)
        xs = np.array([0.0, *anchors])
        ys = np.array([0.0, *(self.conformal_halfwidths[a] for a in anchors)])
        return np.interp(h, xs, ys)

    def predict_with_interval(self, ex: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Returns (predicted_pct, interval_low, interval_high) at the example horizons,
        with per-horizon conformal halfwidths."""
        delta = self.predict_delta(ex)
        pred_pct = ex["current_pct"].to_numpy(dtype=float) + delta
        hw = self._halfwidths_for(ex["horizon"].to_numpy(dtype=float))
        return pred_pct, pred_pct - hw, pred_pct + hw

    def predict_fill_trajectory(
        self, base_features: dict, horizons: Sequence[int]
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Serve arbitrary (daily) horizons honestly from a weekly-trained model.

        The model is only evaluated at the horizons it was actually trained on
        (``trained_horizons``, ~7/14 days with weekly bulletins); a served horizon h is
        the linear interpolation *in h* between the anchor (0, Δ=0) and those trained
        predictions — never a raw model query at an untrained horizon (a tree model
        would silently hand a 1-day query the 7-day delta). Beyond the largest trained
        horizon the delta is held flat (no extrapolated trend claims). Intervals widen
        with horizon via the per-horizon conformal anchors (ADR-0006).

        ``base_features`` must carry the non-horizon FEATURES (current_pct, rate,
        doy_sin, doy_cos, normal_pct, log_capacity).
        """
        if not self.trained_horizons:
            raise ValueError("fit() must run before predict_fill_trajectory()")
        anchor_rows = pd.DataFrame([{**base_features, "horizon": h} for h in self.trained_horizons])
        anchor_delta = self.predict_delta(anchor_rows)
        hs = np.asarray(list(horizons), dtype=float)
        delta = np.interp(
            hs,
            np.array([0.0, *map(float, self.trained_horizons)]),
            np.array([0.0, *anchor_delta]),
        )
        pred_pct = float(base_features["current_pct"]) + delta
        hw = self._halfwidths_for(hs)
        return pred_pct, pred_pct - hw, pred_pct + hw
