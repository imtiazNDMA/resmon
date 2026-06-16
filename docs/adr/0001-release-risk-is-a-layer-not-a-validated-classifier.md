# Release-risk is a transparent layer over the forecast, not a separately-validated classifier

## Context

The product's headline objective is predicting flood/emergency reservoir releases, and the spec originally made *release-event recall, precision, and probability calibration* an acceptance gate (NFR-ACC-3, AC-5).

The authoritative historical dataset (`data/historical/reservoir_timeseries.csv`) is weekly bulletins for three reservoirs over **~11 annual cycles** (2015-07 → 2026-04). That is enough peaks to *backtest* recall on a held-out set — but two facts still keep release-risk from being a live-validated classifier: (1) weekly cadence cannot resolve an actual spillway discharge, so every "release event" is *derived* from the storage series and *weakly labelled* (against the Normal-Storage rule-curve proxy, ADR-0002), and (2) bulletin ground truth **ends in April 2026 and never resumes** (closed loop, ADR-0005), so recall cannot be continuously re-validated and no future release is ever observed live.

*(History note: this ADR was first written when only one annual cycle was on disk (~3 episodes); the dataset was later expanded to 11 years. The decision is unchanged — the live-validation gap, not episode count, is now the governing reason.)*

## Decision

Split the primary objective into two layers and put the testable acceptance contract on the lower one:

1. **Forecast (validated).** The 1–14 day level/volume/fill-% forecast is the measured acceptance gate — walk-forward validation, skill vs persistence/climatology baselines, calibrated prediction intervals (NFR-ACC-2).
2. **Release-risk (backtested, not live-validated).** Risk level is a transparent, explainable function of the forecast trajectory crossing reservoir-specific FRL/threshold bands, net of the rule curve. Recall/precision/lead-time/calibration are reported from the **~11-year historical backtest** (held-out near-FRL episodes), but are **not live acceptance gates** — no production ground truth exists to re-validate them. AC-5 is restated around the historical backtest plus illustrative case studies.

## Consequences

- Release-risk remains the product's headline *feature* and primary user-facing output; only its *acceptance evidence* changes from a statistic to case studies.
- Honesty: the platform never claims a validated false-negative rate it cannot support from the data.
- The forecast layer must be strong, since release-risk inherits all of its skill and uncertainty.
