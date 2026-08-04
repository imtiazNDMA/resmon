# Autoresearch Program: Current Reservoir Level Estimation

Goal: improve current-date reservoir level estimation from processed SAR imagery.

This follows the Karpathy `autoresearch` pattern, adapted to this repo:

- Editable experiment file: `research/current_level_candidate.py`
- Fixed evaluator: `uv run python scripts/autoresearch_current_estimate.py`
- Primary metric: `level_mae_m`, lower is better
- Secondary metrics: `storage_mae_bcm`, `fill_mae_pct`

## Rules

- Edit only `research/current_level_candidate.py` during autonomous experiments.
- Do not edit production pipeline files while experimenting.
- Do not use future bulletins or future observations for a prediction row.
- Preserve the domain target: current estimate for the imagery date, not future forecasting.
- Prefer simple, reviewable models. We have small data.
- Treat extrapolation explicitly; do not hide it by clipping unless the metric improves and the behavior is documented.

## Candidate Contract

`current_level_candidate.py` must expose:

```python
def fit(train_df): ...
def predict(model, rows_df): ...
```

`predict` must return `level_m` and either `live_storage_bcm` or `pct_filled`.

Input columns include:

- `reservoir_id`
- `gt_date`
- `acquisition_date`
- `area_km2`
- `level_m`
- `live_storage_bcm`
- `pct_filled`
- `live_capacity_bcm`
- `area_confidence`
- `extraction_method`

## Experiment Loop

1. Run baseline:
   `uv run python scripts/autoresearch_current_estimate.py`
2. Record `score` and per-reservoir metrics.
3. Modify `research/current_level_candidate.py` only.
4. Rerun the evaluator.
5. Keep the change only if the score improves and no reservoir regresses catastrophically.

Useful experiment ideas:

- monotonic transforms of area before linear fit
- per-reservoir robust regression / outlier trimming
- confidence-weighted fits
- piecewise linear fits near low/high storage regimes
- jointly fit storage and level with physically plausible monotonicity
