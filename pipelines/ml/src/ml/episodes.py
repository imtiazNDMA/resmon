"""Historical release-episode detection + the AC-5 replayed backtest (ADR-0001, §8.3).

Release episodes are derived from the bulletin series (explicit gate logs are
unavailable): a near-FRL peak — plateau-aware — followed by drawdown, weakly labelled
per ADR-0001. The backtest **replays** the forecaster + transparent risk logic through
history with no hindsight: fit strictly before a train cutoff, walk forward through the
held-out period issuing assessments from data available at each base date, then score
those assessments against subsequently observed episodes (hits / misses / false alarms
/ lead time). Episode detection itself may look at the full series — episodes are the
ground-truth labels being scored against, never inputs to the replayed assessments.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.forecaster import MAX_HORIZON, Forecaster, build_examples
from ml.release_risk import assess_release_risk

_ALERT_LEVELS = frozenset({"Watch", "Warning", "Imminent"})


def _near_frl_for(
    reservoir_id: str, thresholds_by_reservoir: dict[str, dict] | None, default: float
) -> float:
    """Per-reservoir near-FRL line: the warning band from release_thresholds where
    available (C8), else the caller-supplied default."""
    thr = (thresholds_by_reservoir or {}).get(reservoir_id) or {}
    band = thr.get("warning") if isinstance(thr, dict) else None
    if isinstance(band, dict) and "pct" in band:
        return float(band["pct"])
    return default


def detect_release_episodes(
    df: pd.DataFrame,
    near_frl_pct: float = 95.0,
    thresholds_by_reservoir: dict[str, dict] | None = None,
) -> list[dict]:
    """Near-FRL fill peaks followed by drawdown (one per high-water excursion).

    Plateau-aware (C8): a maximal run of equal values is one peak, dated at the run's
    *first* index — a sustained 100% fill is an episode, not a gap. Local maxima whose
    surrounding dip never drops below the near-FRL line share one contiguous ≥near-FRL
    run and are merged (highest peak wins). Each episode carries ``onset_date``: the
    first date of the contiguous ≥near-FRL run leading to the peak (the observed
    episode onset the backtest measures lead time against).
    """
    episodes: list[dict] = []
    for rid, g in df.groupby("reservoir_id"):
        near_frl = _near_frl_for(rid, thresholds_by_reservoir, near_frl_pct)
        g = g.sort_values("date").reset_index(drop=True)
        pct = g["pct_filled"].to_numpy(dtype=float)
        n = len(pct)
        best_by_onset: dict[object, dict] = {}
        i = 1
        while i < n:
            if pct[i] >= near_frl and pct[i] >= pct[i - 1]:
                j = i
                while j + 1 < n and pct[j + 1] == pct[i]:
                    j += 1  # plateau: extend the run of equal values
                if j + 1 < n and pct[j + 1] < pct[i]:
                    s = i
                    while s - 1 >= 0 and pct[s - 1] >= near_frl:
                        s -= 1
                    onset = g["date"].iloc[s]
                    cand = {
                        "reservoir_id": rid,
                        "peak_date": g["date"].iloc[i],
                        "peak_pct": float(pct[i]),
                        "onset_date": onset,
                    }
                    prev = best_by_onset.get(onset)
                    if prev is None or cand["peak_pct"] > prev["peak_pct"]:
                        best_by_onset[onset] = cand
                    i = j + 1
                    continue
            i += 1
        episodes.extend(sorted(best_by_onset.values(), key=lambda e: e["peak_date"]))
    return episodes


def backtest_release_risk(
    df: pd.DataFrame,
    thresholds_by_reservoir: dict[str, dict],
    near_frl_pct: float = 95.0,
    train_frac: float = 0.6,
    cal_frac: float = 0.2,
    stride_days: int = 7,
    match_window_days: int = MAX_HORIZON,
) -> dict:
    """Replayed (hindsight-free) AC-5 backtest of the release-risk layer.

    Design choice (documented): a **single train cutoff + rolling-origin replay**, not
    a per-base-date refit. With ~194 weekly rows per reservoir, refitting at every base
    date adds hundreds of model fits without changing what is measured (the transparent
    risk logic over a Δ-fill forecast); the single cutoff keeps the replay strictly
    causal — the model and its conformal calibration only ever see examples whose
    ``target_date`` precedes the first replayed base date.

    Replay: at each bulletin date after the cutoff (subsampled to ``stride_days``),
    build the feature row from data available *at that date only*, forecast
    1..MAX_HORIZON days with ``Forecaster.predict_fill_trajectory``, and run
    ``assess_release_risk`` against the reservoir's thresholds.

    Scoring against observed episodes (labels detected with hindsight — they are the
    ground truth, not replay inputs):

    - **hit**: an episode whose most recent Watch+ assessment before/at onset lies
      within ``match_window_days`` of it. Lead time = onset − the first base date of
      the contiguous Watch+ run ending at that assessment ("first Watch+ risk date vs
      observed episode onset").
    - **miss**: an episode with no such assessment.
    - **false alarm**: a Watch+ assessment not consumed by a hit and with no episode
      onset within ``match_window_days`` ahead, and not issued while an episode was
      active (onset → peak + ``match_window_days`` grace). Alerts too close to the end
      of the series to adjudicate are counted ``unresolved_alerts`` instead.

    Requires df columns: reservoir_id, date, pct_filled, normal_storage_pct,
    live_capacity_bcm. Returns ``{"evaluated": False, "reason": ...}`` when history is
    too short to train + replay.
    """
    df = df.sort_values(["reservoir_id", "date"]).reset_index(drop=True)
    dates = np.sort(df["date"].unique())
    if len(dates) < 20:
        return {"evaluated": False, "reason": "insufficient history"}
    cutoff = pd.Timestamp(dates[int(len(dates) * train_frac)])
    cal_start = pd.Timestamp(dates[int(len(dates) * (train_frac - cal_frac))])

    ex = build_examples(df)
    # Purged split: no fit example's target crosses into calibration, none of either
    # crosses the cutoff into the replay period.
    fit_ex = ex[ex["target_date"] < cal_start]
    cal_ex = ex[(ex["base_date"] >= cal_start) & (ex["target_date"] <= cutoff)]
    if len(fit_ex) < 30 or len(cal_ex) < 10:
        return {"evaluated": False, "reason": "insufficient training/calibration examples"}
    fc = Forecaster().fit(fit_ex)
    fc.conformalize(cal_ex)

    horizons = list(range(1, MAX_HORIZON + 1))
    assessments: list[dict] = []
    for rid, g in df.groupby("reservoir_id"):
        thresholds = thresholds_by_reservoir.get(rid)
        if not thresholds:
            continue
        g = g.sort_values("date").reset_index(drop=True)
        pct = g["pct_filled"].to_numpy(dtype=float)
        normal = g["normal_storage_pct"].to_numpy(dtype=float)
        cap = float(g["live_capacity_bcm"].iloc[0])
        last_base: pd.Timestamp | None = None
        for i in range(1, len(g)):
            d = g["date"].iloc[i]
            if d <= cutoff:
                continue
            if last_base is not None and (d - last_base).days < stride_days:
                continue
            last_base = d
            dd = (d - g["date"].iloc[i - 1]).days
            rate = (pct[i] - pct[i - 1]) / dd if dd > 0 else 0.0
            doy = d.timetuple().tm_yday
            norm_i = normal[i] if not np.isnan(normal[i]) else pct[i]
            base_features = {
                "current_pct": pct[i],
                "rate": rate,
                "doy_sin": np.sin(2 * np.pi * doy / 365.0),
                "doy_cos": np.cos(2 * np.pi * doy / 365.0),
                "normal_pct": norm_i,
                "log_capacity": np.log(cap),
            }
            pred, low, high = fc.predict_fill_trajectory(base_features, horizons)
            risk = assess_release_risk(
                horizons, pred.tolist(), low.tolist(), high.tolist(), thresholds, norm_i, pct[i]
            )
            assessments.append(
                {
                    "reservoir_id": rid,
                    "base_date": d,
                    "risk_level": risk.risk_level,
                    "release_probability": risk.release_probability,
                    "forecast_lead_days": risk.estimated_lead_time_days,
                }
            )

    all_episodes = detect_release_episodes(df, near_frl_pct, thresholds_by_reservoir)
    eval_episodes = [ep for ep in all_episodes if ep["onset_date"] > cutoff]

    by_rid: dict[str, list[dict]] = {}
    for a in assessments:
        by_rid.setdefault(a["reservoir_id"], []).append(a)

    scored: list[dict] = []
    consumed: set[tuple[str, pd.Timestamp]] = set()
    for ep in eval_episodes:
        rid, onset = ep["reservoir_id"], ep["onset_date"]
        seq = by_rid.get(rid, [])
        alert_idxs = [
            k
            for k, a in enumerate(seq)
            if a["base_date"] <= onset and a["risk_level"] in _ALERT_LEVELS
        ]
        hit = False
        lead: int | None = None
        if alert_idxs and (onset - seq[alert_idxs[-1]]["base_date"]).days <= match_window_days:
            hit = True
            k = alert_idxs[-1]
            while k - 1 >= 0 and seq[k - 1]["risk_level"] in _ALERT_LEVELS:
                k -= 1  # walk back through the contiguous alerting run
            lead = int((onset - seq[k]["base_date"]).days)
            consumed.update((rid, seq[j]["base_date"]) for j in range(k, alert_idxs[-1] + 1))
        scored.append({**ep, "hit": hit, "lead_time_days": lead})

    series_end = df["date"].max()
    false_alarms = 0
    unresolved = 0
    for a in assessments:
        if a["risk_level"] not in _ALERT_LEVELS:
            continue
        rid, b = a["reservoir_id"], a["base_date"]
        if (rid, b) in consumed:
            continue
        justified = any(
            0 <= (ep["onset_date"] - b).days <= match_window_days
            or (
                ep["onset_date"] <= b
                and b <= ep["peak_date"] + pd.Timedelta(days=match_window_days)
            )
            for ep in all_episodes
            if ep["reservoir_id"] == rid
        )
        if justified:
            continue
        if (series_end - b).days < match_window_days:
            unresolved += 1  # right-censored: an episode may begin after the data ends
        else:
            false_alarms += 1

    hits = sum(1 for ep in scored if ep["hit"])
    leads = [ep["lead_time_days"] for ep in scored if ep["hit"]]
    return {
        "evaluated": True,
        "train_cutoff": cutoff.date().isoformat(),
        "n_assessments": len(assessments),
        "n_episodes": len(scored),
        "hits": hits,
        "misses": len(scored) - hits,
        "false_alarms": false_alarms,
        "unresolved_alerts": unresolved,
        "mean_lead_days": float(np.mean(leads)) if leads else None,
        "episodes": scored,
        "assessments": assessments,
    }
