# Forecaster: pooled Δ-fill, inflow-aware, direct multi-horizon, conformal intervals

## Context

The forecast is the validated core of the product (ADR-0001). The data is three reservoirs over ~11 years of weekly bulletins, plus interleaved SAR acquisitions; production is closed-loop (ADR-0005), so the forecaster is initialized from SAR-derived (rating-curve-mapped) state, not bulletins. Storage targets are ~weekly, while the promised horizon is daily (1–14).

## Decision

- **(a) Pooled global model on `pct_filled`**, not per-reservoir. Fill-% is comparable across reservoirs of very different absolute size, so pooling multiplies effective sample size; reservoir-specific features (FRL, capacity, catchment area, snow fraction) let it still differentiate. Per-reservoir bias terms only if walk-forward justifies them.
- **(b) Predict Δ`pct_filled` over horizon h, inflow-aware, direct multi-horizon** (horizon as a feature, one model spans 1–14). The Δ target stops the model echoing current level (that is persistence's job) and forces it to learn the precip/melt inflow signal. Light **mass-balance structure**: net predicted inflow against the Normal-Storage recession (rule-curve proxy, ADR-0002) as expected outflow. Start with a **regularized gradient-boosted regressor**; add capacity only when validation earns it. **Trained on SAR-derived state** (ADR-0005) for train/serve consistency. Baselines to beat: **persistence and Normal-Storage climatology** (NFR-ACC-2).
- **(c) Conformal prediction intervals** (split / walk-forward conformalized residuals), not parametric Gaussian — small, non-normal residuals; conformal gives finite-sample calibration, feeding release-risk's calibration requirement.

Horizon resolution is effectively ~weekly (target cadence), interpolated to daily with intervals that widen between observation dates.

## Consequences

- One model to train, validate, and monitor; cold-start for a new reservoir is the pooled model + its static features until local history accrues.
- The Δ-target plus mass-balance framing keeps the model explainable — contributing factors (precip, melt, rate-of-rise) fall out naturally for release-risk.
- Rejected: per-reservoir models (overfit on ~195 obs each), absolute-level targets (echo persistence), parametric intervals (miscalibrated on non-normal residuals), recursive multi-step (error accumulation on a weekly target grid).
