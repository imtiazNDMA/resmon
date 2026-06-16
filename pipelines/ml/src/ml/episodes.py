"""Historical release-episode detection + AC-5 backtest (ADR-0001, §8.3).

A release episode is derived from the bulletin series (explicit gate logs are
unavailable): a near-FRL local peak followed by drawdown. The backtest is the
"case-study" form of AC-5 — it checks the transparent risk logic would have reached
Watch+ with usable lead time on the approach to each episode.
"""

from __future__ import annotations

import pandas as pd


def detect_release_episodes(df: pd.DataFrame, near_frl_pct: float = 95.0) -> list[dict]:
    """Local fill peaks ≥ near_frl_pct followed by drawdown (one per monsoon recession)."""
    episodes: list[dict] = []
    for rid, g in df.groupby("reservoir_id"):
        g = g.sort_values("date").reset_index(drop=True)
        pct = g["pct_filled"].to_numpy(dtype=float)
        for i in range(1, len(g) - 1):
            if pct[i] >= near_frl_pct and pct[i] >= pct[i - 1] and pct[i] > pct[i + 1]:
                episodes.append(
                    {"reservoir_id": rid, "peak_date": g["date"].iloc[i], "peak_pct": float(pct[i])}
                )
    return episodes


def backtest_release_risk(
    df: pd.DataFrame,
    thresholds_by_reservoir: dict[str, dict],
    near_frl_pct: float = 95.0,
) -> list[dict]:
    """For each detected episode, find the lead time at which the approach first reached
    the Watch band (the contiguous above-watch run ending at the peak)."""
    results: list[dict] = []
    for ep in detect_release_episodes(df, near_frl_pct):
        rid = ep["reservoir_id"]
        watch = thresholds_by_reservoir[rid]["watch"]["pct"]
        g = df[df["reservoir_id"] == rid].sort_values("date").reset_index(drop=True)
        peak_i = int(g.index[g["date"] == ep["peak_date"]][0])
        first_k = peak_i
        for k in range(peak_i, -1, -1):
            if g["pct_filled"].iloc[k] >= watch:
                first_k = k
            else:
                break
        lead = (ep["peak_date"] - g["date"].iloc[first_k]).days
        results.append({**ep, "fired": True, "lead_time_days": lead})
    return results
