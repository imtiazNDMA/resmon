# Closed loop: bulletins are historical bootstrap only; production has no live ground truth

## Context

The historical bulletin record (~11 years, 2015-07 → 2026-04, three reservoirs) is the only ground truth that will ever exist — there is no access to current or future bulletins. The platform must therefore *replace* bulletins, not depend on them continuing.

## Decision

Treat bulletins as a **one-time training/calibration corpus**. Production runs as a **closed loop** on SAR + DEM + catchment forcing → models, with no bulletin input ever again:

- The **estimation bridge** (the blended rating curve, ADR-0004, fit from ~11 years of paired SAR-area ↔ bulletin-storage) is the *sole* production path from SAR `surface_area` to storage/level. Its historical validation error is the production accuracy ceiling.
- The **forecaster is initialized from SAR-derived (rating-curve-mapped) state**, and is trained on that same SAR-derived state — not raw bulletin values — to avoid train/serve skew (same logic as GFS reforecasts, ADR-0003 v2).
- **Accuracy is established once, by historical backtest** (walk-forward over ~11 years). Post-deployment "validation" is **internal-consistency & drift monitoring** only: SAR-derived vs forecast residuals, extraction-confidence trends, feature drift, implausible jumps. There is no live ground-truth comparison.

## Consequences

- The rating curve and SAR water extraction are the highest-risk components; everything downstream inherits their error with no corrective feedback in production.
- FR-ML-6, NFR-ACC-4, §8.4 are reframed from "continuous validation against incoming bulletins" to "historical backtest + internal-consistency monitoring."
- Release-risk cannot be live-validated (reinforces ADR-0001).
- A future return of bulletins (or a new gauge feed) would be a strict upgrade — re-enabling live validation and curve re-fitting — but is not assumed.
