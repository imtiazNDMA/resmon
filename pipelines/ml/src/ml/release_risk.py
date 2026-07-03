"""Release-risk layer (FR-ML-3, §8.3, ADR-0001) — the platform's primary output.

A **transparent function over the forecast**, not a trained classifier: the forecast
fill trajectory is compared to per-reservoir FRL/threshold bands, **net of the
Normal-Storage rule curve** (flood/emergency vs routine drawdown, §8.3). It outputs a
discrete risk level, a heuristic risk index, the estimated lead time, and the
contributing factors that make the call explainable for disaster-management decisions.

IMPORTANT — ``release_probability`` is an **UNCALIBRATED heuristic risk index** in
[0, 1], not a calibrated event probability. It is the fraction of the conformal
prediction interval, at the peak-forecast horizon, that lies above the warning
threshold: interpretable (0 = whole interval below warning, ~0.5 = point forecast on
the warning line for a symmetric interval, 1 = whole interval clear of it) and monotone
in the forecast level. Calibrating it into a real probability requires the replayed
historical backtest (``ml.episodes.backtest_release_risk``), which supplies the
hit/miss/false-alarm counts to calibrate against; until that is run on real (non-
synthetic) forcing, treat the value as an ordinal index.
"""

from __future__ import annotations

from dataclasses import dataclass

RISK_LEVELS = ("Low", "Watch", "Warning", "Imminent")
# When a trajectory carries no conformal interval at all we refuse to claim certainty
# and assume this halfwidth (fill-%) instead — a missing interval is missing
# uncertainty, never zero uncertainty (C7).
FALLBACK_HALFWIDTH_PCT = 5.0


@dataclass(frozen=True)
class RiskAssessment:
    risk_level: str
    release_probability: float
    estimated_lead_time_days: float | None
    contributing_factors: dict


def risk_band(pct: float, thresholds: dict) -> str:
    """Map a fill-% to a band using the reservoir's release thresholds (D7)."""
    if pct >= thresholds["imminent"]["pct"]:
        return "Imminent"
    if pct >= thresholds["warning"]["pct"]:
        return "Warning"
    if pct >= thresholds["watch"]["pct"]:
        return "Watch"
    return "Low"


def assess_release_risk(
    horizons_days: list[int],
    pred_pct: list[float],
    interval_low: list[float | None],
    interval_high: list[float | None],
    thresholds: dict,
    normal_pct: float,
    current_pct: float,
) -> RiskAssessment:
    """Translate a 1–14 day forecast trajectory into a release-risk assessment.

    One consistent basis — the point-forecast trajectory and its conformal interval at
    the peak-forecast horizon:

    - **Risk level**: band of the point-forecast peak (transparent, ADR-0001).
    - **Lead time**: first horizon whose point forecast crosses the watch band.
    - **Risk index** (``release_probability``, UNCALIBRATED — see module docstring):
      fraction of the conformal interval at the peak horizon lying above the warning
      threshold.
    - **Rule-curve damping** (documented heuristic, §8.3 / ADR-0002): if the forecast
      peak does not exceed the seasonal Normal-Storage level the state is routine
      seasonal high water, not a flood-class approach, and the index is halved.
    - **Consistency guard**: if no watch crossing exists (lead is None) the index is
      capped at 0.5, so index > 0.5 always implies a non-None lead time.

    Missing interval bounds (C7) are treated as missing uncertainty: the peak-horizon
    interval is imputed symmetric with the widest halfwidth present elsewhere in the
    trajectory, or FALLBACK_HALFWIDTH_PCT if no interval exists at all — never
    collapsed onto the point forecast.
    """
    watch = float(thresholds["watch"]["pct"])
    warning = float(thresholds["warning"]["pct"])

    pred = [float(p) for p in pred_pct]
    k = max(range(len(pred)), key=lambda idx: pred[idx])
    peak = pred[k]
    level = risk_band(peak, thresholds)

    lead: float | None = None
    for h, p in zip(horizons_days, pred, strict=True):
        if p >= watch:
            lead = float(h)
            break

    if interval_low[k] is not None and interval_high[k] is not None:
        lo_k, hi_k = float(interval_low[k]), float(interval_high[k])  # type: ignore[arg-type]
    else:
        known = [
            (float(hi) - float(lo)) / 2.0
            for lo, hi in zip(interval_low, interval_high, strict=True)
            if lo is not None and hi is not None
        ]
        halfwidth = max(known) if known else FALLBACK_HALFWIDTH_PCT
        lo_k, hi_k = peak - halfwidth, peak + halfwidth

    width = hi_k - lo_k
    if width <= 0:  # degenerate interval — fall back to a step on the point forecast
        frac_above = 1.0 if peak >= warning else 0.0
    else:
        frac_above = (hi_k - warning) / width
    frac_above = min(max(frac_above, 0.0), 1.0)

    prob = frac_above
    above_normal = peak - normal_pct
    if above_normal <= 0:  # routine seasonal state, not a flood-class approach
        prob *= 0.5
    if lead is None:  # consistency: index > 0.5 must imply an estimated lead
        prob = min(prob, 0.5)
    prob = float(min(max(prob, 0.0), 1.0))

    factors = {
        "current_fill_pct": round(current_pct, 2),
        "forecast_peak_pct": round(peak, 2),
        "forecast_peak_horizon_days": int(horizons_days[k]),
        "forecast_peak_upper_pct": round(hi_k, 2),
        "forecast_peak_lower_pct": round(lo_k, 2),
        "interval_fraction_above_warning": round(frac_above, 4),
        "band_crossed": level,
        "above_seasonal_normal_pct": round(above_normal, 2),
        "watch_threshold_pct": watch,
        "warning_threshold_pct": warning,
        "lead_time_days": lead,
        "probability_basis": "uncalibrated interval-fraction heuristic (ml.release_risk)",
    }
    return RiskAssessment(level, prob, lead, factors)
