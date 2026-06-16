"""Release-risk layer (FR-ML-3, §8.3, ADR-0001) — the platform's primary output.

A **transparent function over the forecast**, not a trained classifier: the forecast
fill trajectory is compared to per-reservoir FRL/threshold bands, **net of the
Normal-Storage rule curve** (flood/emergency vs routine drawdown, §8.3). It outputs a
discrete risk level, an (uncertainty-aware) probability, the estimated lead time, and the
contributing factors that make the call explainable for disaster-management decisions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

RISK_LEVELS = ("Low", "Watch", "Warning", "Imminent")
_PROB_SCALE = 5.0  # fill-% margin over the warning band that maps to ~0.73 probability


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


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def assess_release_risk(
    horizons_days: list[int],
    pred_pct: list[float],
    interval_high: list[float],
    thresholds: dict,
    normal_pct: float,
    current_pct: float,
) -> RiskAssessment:
    """Translate a 1–14 day forecast trajectory into a release-risk assessment.

    Risk level = band of the forecast peak. Lead time = first horizon crossing the watch
    band. Probability scales with how far the *upper* (conformal) interval exceeds the
    warning band, and is damped when the peak is not above the seasonal normal (routine,
    not flood-class — the rule-curve net-out of §8.3)."""
    watch = thresholds["watch"]["pct"]
    warning = thresholds["warning"]["pct"]

    peak = max(pred_pct)
    peak_high = max(interval_high)
    level = risk_band(peak, thresholds)

    lead: float | None = None
    for h, p in zip(horizons_days, pred_pct, strict=False):
        if p >= watch:
            lead = float(h)
            break

    above_normal = peak - normal_pct
    prob = _logistic((peak_high - warning) / _PROB_SCALE)
    if above_normal <= 0:  # routine seasonal state, not a flood-class approach
        prob *= 0.5
    prob = float(min(max(prob, 0.0), 1.0))

    factors = {
        "current_fill_pct": round(current_pct, 2),
        "forecast_peak_pct": round(peak, 2),
        "forecast_peak_upper_pct": round(peak_high, 2),
        "band_crossed": level,
        "above_seasonal_normal_pct": round(above_normal, 2),
        "watch_threshold_pct": watch,
        "warning_threshold_pct": warning,
        "lead_time_days": lead,
    }
    return RiskAssessment(level, prob, lead, factors)
