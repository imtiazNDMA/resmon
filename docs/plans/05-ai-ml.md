# Plan 05 — AI / ML / DL Implementation Plan

**Track:** ML / Data Science (`pipelines/ml/`)
**Status:** Draft for review
**Owner:** ML engineering
**Depends on:** Data Engineering (ABT + `ForecastForcing`), Remote Sensing (`Observation`), DB team (canonical entities), Frozen contracts ([ADR-0003](../adr/0003-frozen-pipeline-contracts.md))
**Governing constraints:** small-data + closed-loop ([ADR-0005](../adr/0005-closed-loop-no-live-ground-truth.md)); §8.5

> **Planning only.** This document specifies the ML pipeline design, contracts, and task breakdown. No application code is produced here.

---

## 1. Scope & owned requirements

This track owns the **calibration → estimation → forecasting → release-risk** model chain and its lifecycle (MLflow, retraining, drift). It reads the Unified Analytical Base Table (§6.7) and `ForecastForcing`, and writes the canonical `RatingCurve`, `Prediction`, `ReleaseRisk`, and `GroundTruthMatch` entities owned by the DB team.

**Owned functional requirements**

| Group | IDs | What this track delivers |
| --- | --- | --- |
| Ground-truthing & calibration | **FR-GT-1…7** | Temporal nearest-match, ML-extraction validation, **empirical area↔storage↔level rating-curve construction blended with a DEM prior/extrapolation backstop**, extraction-method selection, weak-label generation, acceptance gating |
| Estimation | **FR-ML-1** | Calibrated area→volume→level mapping (the *estimation bridge*) |
| Forecasting | **FR-ML-2** | 1–14 day inflow-aware fill-% forecast with conformal intervals |
| Release prediction (primary) | **FR-ML-3** | Flood/emergency release probability, risk level, lead time, contributing factors, calibration |
| Lifecycle | **FR-ML-4, FR-ML-5, FR-ML-6** | MLflow tracking/registry, automated inference, drift/internal-consistency monitoring |

**Owned non-functional / acceptance**

- **NFR-ACC-1** (estimation MAE gate), **NFR-ACC-2** (forecast skill vs baseline), **NFR-ACC-3** (release recall/lead-time/calibration — *backtest only*, not a live gate), **NFR-ACC-4** (drift-only live metrics).
- **NFR-TEST-3** (end-to-end backtest against a known near-FRL/release episode).
- **NFR-MNT-2** (all runs reproducible via MLflow).
- **AC-2** (foundational gate), **AC-3**, **AC-4**, **AC-5 (primary)**.

**Boundary (NOT owned here)**

- SAR preprocessing and the *running* of the water extractor (FR-RS-2/3) belong to Remote Sensing. **This track owns the *selection harness* (FR-GT-5 / [ADR-0007](../adr/0007-water-extraction-harness.md))** — it evaluates extractor candidates end-to-end and tells RS which one to register, but RS executes extraction.
- The ABT build (FR-DE-12 / FR-ABT-*) and catchment forcing belong to Data Engineering. This track *consumes* it and states the feature requirements (see §7, open decisions).
- Persisting/serving via API belongs to the API track; this track defines the inference interface and output schemas it calls.

---

## 2. Upstream dependencies (what must exist before we train)

### 2.1 ABT contract (`docs/contracts/observation-and-abt.md`, `contract_version: 2`)
The single training/inference dataset. We bind to it exactly; a column change is a coordinated `contract_version` bump.

- **`AnalyticalBaseTable`** — grain `(reservoir_id, date)` on a continuous daily IST calendar. Ground-truth + SAR columns are sparse (populated only on their dates), with `days_since_bulletin` / `days_since_acquisition` recency. Carries forcing (`catchment_precip`, `antecedent_precip_index`, `snow_cover_area`, `swe`, `degree_day_melt`), provenance (`is_extrapolated`, `residual_vs_ground_truth`, `freshness_flags`, `row_quality`, `abt_version`), and reservoir statics (`frl`, `live_capacity_bcm`, `normal_storage_pct`).
- **`ForecastForcing`** — horizon-keyed `(reservoir_id, issue_date, horizon 1–14)`: `forecast_precip`, `forecast_degree_day_melt`, `gfs_run_cycle`. Point-in-time reforecast from GEE `NOAA/GFS0P25` (archive ≥ 2015-07). The forecaster joins it on `issue_date = date`. **This is what removes train/serve skew (§8.2): both train and serve build GFS features identically.**
- **Stub rule:** synthetic `Observation` rows (`extraction_method = 'stub'`) let us develop and smoke-test before real SAR lands; we filter them out of any accepted training/eval run.

### 2.2 DB schema (canonical entities we write)
`RatingCurve`, `GroundTruthMatch`, `Prediction`, `ReleaseRisk` per §6.3. Reservoir statics we read: `frl`, `live_capacity_bcm`, release thresholds, seasonal rule curve (Normal-Storage proxy, [ADR-0002](../adr/0002-normal-storage-as-rule-curve-proxy.md)).

### 2.3 RS extraction outputs
`Observation` rows (`surface_area`, `area_confidence`, `extraction_method/version`, `layover_shadow_fraction`, `orbit_relative`, `pass_direction`). The DEM hypsometric *shape* (area(elev), incremental volume(elev) above the DEM-epoch waterline) per [ADR-0004](../adr/0004-blended-rating-curve-dem-empirical.md) — produced by RS/DEM tooling, consumed by our rating-curve blend step.

---

## 3. Downstream consumers

- **API track** calls our **inference interface** (§9.3) and reads persisted `Prediction` / `ReleaseRisk` / `RatingCurve` / `GroundTruthMatch`. Serves forecasts, release-risk (probability, level, lead time, contributing factors), accuracy metrics, and the AC-2 gate status.
- **Frontend** renders forecast charts + intervals (FR-UI-3), release-risk outlook + map markers, estimate-vs-ground-truth accuracy (FR-UI-4), early-warning alerts (FR-UI-6). Alerting logic (threshold crossing → `Alert`) is downstream of `ReleaseRisk`; we expose `risk_level` and `estimated_lead_time_days` as its trigger inputs.
- **Audit trail (NFR-REL-5)**: every persisted prediction carries `run_timestamp`, `model_version`, and `abt_version` so "what was predicted, when, on which data and model" is reconstructable.

---

## 4. Modelling design (centerpiece)

Four stages, each a distinct MLflow experiment. The chain is **strictly ordered**: the rating curve must pass its gate (AC-2 / NFR-ACC-1) before forecasting and release-risk are production-ready (FR-GT-7).

### Stage A — Ground-truthing & rating-curve calibration (FR-GT-1…7)

This is the foundation. Production is closed-loop: the rating curve is the *sole* path from SAR area to storage, so its historical error is the production accuracy ceiling ([ADR-0005](../adr/0005-closed-loop-no-live-ground-truth.md)).

**A.1 Temporal nearest-match (FR-GT-1).** For each bulletin `(reservoir, gt_date)`, find the nearest `Observation` over the AOI; reject pairs with `|time_gap| > N` days (configurable, default ±N from config); record `time_gap_days`. Write `GroundTruthMatch` rows.

**A.2 ML extraction on matched scenes (FR-GT-2).** Extraction is *run by RS*; here we consume the extracted `surface_area` + `area_confidence` per candidate extractor for the matched scenes.

**A.3 Indirect validation (FR-GT-3).** Bulletins record level/volume, never area, so validation is always indirect: convert extracted area → derived volume/level/`pct_filled` via the curve, compare to the paired bulletin, store `residual_vs_ground_truth`.

**A.4 Empirical rating-curve construction, blended (FR-GT-4 / [ADR-0004](../adr/0004-blended-rating-curve-dem-empirical.md)).** Per reservoir, build `area↔storage(BCM)` and `area↔level(m)`:

- **Empirical fit (owns observed range):** regress `extracted_area` against bulletin `current_level`, `current_live_storage_bcm`, `pct_filled` from matched pairs. Model family: **monotone-constrained smoother** — isotonic regression or a monotone spline (water area is monotone-increasing in storage/level). Anchor the top with FRL + full live capacity at FRL (area/storage/level at FRL bound the curve). This absorbs SAR-extraction bias + real basin behaviour. Weight points by `area_confidence` and inverse `time_gap_days`.
- **DEM prior (owns above-observed-max → FRL):** flood the DEM in the AOI from the DEM-epoch waterline (estimated from the bulletin level nearest the Copernicus GLO-30 epoch) up to FRL → `area(elev)`, integrate → incremental `volume(elev)`. DEM supplies *shape*; the empirical curve's storage at the waterline supplies the absolute offset. DEM never supplies submerged volume.
- **Blend:** empirical owns the observed range; in the overlap (waterline → observed max) DEM-vs-empirical agreement is a validation metric (on divergence beyond tolerance, trust empirical and flag); above the observed max DEM is the primary extrapolator into the near-FRL release zone.
- **Persist** `RatingCurve` (`fit_type='blended'`, params/points, FRL/capacity anchors, observed-vs-extrapolated range, DEM-epoch waterline, fit metrics, `version`). Live capacity is time-varying (sedimentation) → curve carries a validity date and is periodically re-fit.

**A.5 Extraction-method selection — joint pipeline harness (FR-GT-5 / [ADR-0007](../adr/0007-water-extraction-harness.md)).** Resolve the chicken-and-egg (curve depends on extractor areas, extractor judged by derived storage) by giving **each candidate its own co-fit blended rating curve**, then comparing the end-to-end `(extractor + its curve)` pipeline:

- **Candidates (staged):** cold-start unsupervised — `Otsu-VH`, `K-means[VV,VH]`, `GMM[VV,VH]`; a **U-Net** added *later*, trained on weak labels (A.6), promoted only if it beats the incumbent on the same holdout.
- **Selection metric:** derived **fill-% MAE vs bulletins** on a **walk-forward / leave-one-season-out holdout**, **broken out by season/regime** (monsoon / winter-ice / wind-roughened). Prefer the *robust* pipeline, not the lowest-mean — a method that collapses on winter ice is disqualified for a year-round system.
- Track all candidates + per-regime metrics in MLflow; register the winner; keep extraction pluggable & versioned (we hand RS the winning `extraction_method/version`).

**A.6 Weak-label generation (FR-GT-6).** Retain validated masks/areas from high-confidence, low-residual pairs as weak labels for the supervised U-Net. Emit a versioned weak-label set artifact for the RS/segmentation track.

**A.7 Acceptance gating (FR-GT-7 / AC-2).** Expose validation MAE on `pct_filled`/volume as a **gate**: compute per-reservoir and fleet-wide; compare to NFR-ACC-1 tolerance (target **fill-% MAE ≤ 5–10%**, final value confirmed during calibration). Publish a machine-readable `gt_gate_status` (pass/fail per reservoir + overall) consumed by the API. Forecasting and release-risk are marked production-ready only when this passes.

| Aspect | Choice |
| --- | --- |
| Features | matched `extracted_area`, `area_confidence`, `time_gap_days`; bulletin `level`/`storage`/`pct_filled`; FRL/capacity anchors; DEM `area(elev)` shape |
| Model family | monotone isotonic / monotone spline (empirical) + DEM-flood geometry (prior); **not a neural net** — the bridge is smooth and low-dimensional |
| Validation | walk-forward / leave-one-season-out; per-regime breakout |
| Metrics | fill-% MAE/RMSE, volume MAE, level MAE; DEM-vs-empirical overlap divergence |
| Uncertainty | residual envelope from holdout; widened in the extrapolated (above-observed-max) band; `is_extrapolated` flag carried downstream |

### Stage B — Estimation (FR-ML-1)

Thin deterministic application of the promoted `RatingCurve` to each new `Observation.surface_area` → calibrated volume (BCM), level (m), `pct_filled`, with an `is_extrapolated` indicator when above the observed max. This is the *estimation bridge* — the closed-loop production path from SAR to storage. No separate training beyond Stage A; estimation is curve inference plus quality flags. Output feeds the ABT's satellite-derived columns and seeds the forecaster's initial state.

### Stage C — Forecasting (FR-ML-2 / §8.2 / [ADR-0006](../adr/0006-forecaster-pooled-delta-fill-conformal.md))

The **validated core** of the product ([ADR-0001](../adr/0001-release-risk-is-a-layer-not-a-validated-classifier.md)); release-risk inherits all its skill and uncertainty.

| Aspect | Choice |
| --- | --- |
| Target | **Δ`pct_filled` over horizon h** (not absolute level — Δ stops the model echoing persistence and forces it to learn the inflow signal) |
| Model | **single pooled model across the 3 reservoirs**, **direct multi-horizon** (horizon as a feature, one model spans 1–14). Start **regularized gradient-boosted regressor** (e.g. LightGBM with monotone/L1-L2 reg); per-reservoir bias terms only if walk-forward earns them; add capacity only when validation justifies it |
| Inflow-awareness | catchment forcing (`catchment_precip`, `antecedent_precip_index`, `snow_cover_area`, `swe`, `degree_day_melt`) + **`ForecastForcing`** (`forecast_precip`, `forecast_degree_day_melt`) joined on `issue_date = date` |
| Mass-balance structure | net predicted inflow against the Normal-Storage recession (rule-curve proxy) as expected outflow; include evaporation as an outflow term where estimable (non-trivial in summer) |
| Train/serve consistency | **train on archived GFS reforecasts** (same `ForecastForcing` construction at train and serve) **and on SAR-derived state**, not raw bulletins ([ADR-0005](../adr/0005-closed-loop-no-live-ground-truth.md)) — the two skew sources both closed |
| Reservoir differentiation | static features: FRL, capacity, catchment area, snow fraction |
| Uncertainty | **conformal prediction intervals** (split / walk-forward conformalized residuals) — finite-sample calibration on small, non-normal residuals; feeds release-risk calibration |
| Baselines to beat | **persistence** and **Normal-Storage climatology** (NFR-ACC-2 / AC-4) |
| Horizon resolution | effectively ~weekly (target cadence), interpolated to daily with intervals widening between observation dates |
| Features (engineered) | recent rate-of-change, lagged storage, day-of-year/seasonality, `days_since_acquisition` recency, antecedent index |
| Validation | expanding-window walk-forward + leave-one-season-out; time-based split, no leakage across the horizon |
| Metrics | MAE/RMSE/MAPE on fill-%/volume/level per horizon; **skill score vs persistence & climatology**; interval coverage (PICP) and width (calibration of conformal intervals) |

Training rows = ABT dates where a storage target exists (SAR-derived, rating-curve-mapped). One model to train, validate, monitor; cold-start for a new reservoir is the pooled model + its static features until local history accrues.

### Stage D — Release prediction (primary) (FR-ML-3 / §8.3 / [ADR-0001](../adr/0001-release-risk-is-a-layer-not-a-validated-classifier.md))

**Release-risk is a transparent layer over the forecast, not a separately-trained classifier.** It is the headline user-facing output but its acceptance evidence is a backtest, not a live statistic.

**D.1 Release taxonomy (critical).** Distinguish a **flood/emergency spillway release** (the disaster signal) from a **routine operational release** (year-round, below FRL, tracking the rule curve). Alerts target the flood class only; conflating the two causes both missed warnings and alarm fatigue. Operational drawdown is modelled as expected outflow.

**D.2 Event definition / weak labels.** A release event is *never directly observed* in weekly bulletins — always inferred. Define a release **episode** from the storage series: storage at/near FRL (or projected beyond safe storage) **and** receding faster than / further below the seasonal Normal-Storage recession (rule-curve proxy, [ADR-0002](../adr/0002-normal-storage-as-rule-curve-proxy.md)), **net of rule-curve drawdown**. Labels are weak/noisy; treat early versions as decision-support, not sole authority. The v1 dataset holds **~3 release episodes** — the unit AC-5 backtests against.

**D.3 Risk computation.** Translate the forecast `pct_filled`/storage trajectory and its conformal interval into a **flood-class release probability** over the horizon (probability the trajectory crosses the FRL/threshold band net of rule curve). Map to discrete **risk levels** (Low / Watch / Warning / Imminent) via reservoir-specific threshold bands. Compute **estimated lead time** (days until the band crossing).

| Aspect | Choice |
| --- | --- |
| Probability | derived from forecast trajectory + conformal interval crossing FRL/threshold bands, net of rule-curve recession |
| Calibration | isotonic / Platt **or** inherit conformal calibration from the forecast layer; report reliability |
| Optimisation target | **maximise recall on actual flood/emergency releases** at the required lead time (target ≥ 2–3 days); keep false alarms tolerable |
| Metrics | **precision-recall** (NOT ROC — event rarity); lead-time distribution; calibration/reliability; **reported from the ~11-year backtest on held-out near-FRL episodes** |
| Class imbalance | class weighting / threshold tuning; treat derived labels as noisy |
| Explainability | every output exposes **contributing factors** (current fill vs FRL, forecast precip, snowmelt/degree-day melt, rate-of-rise) — a hard requirement for accountable disaster decisions |
| Acceptance | **backtest + illustrative case studies** (AC-5 / [ADR-0001](../adr/0001-release-risk-is-a-layer-not-a-validated-classifier.md)); recall/precision/lead-time/calibration are NOT live gates (closed loop) |

---

## 5. Small-data discipline (governing — §8.5)

The regime is ~weekly bulletins, **3 reservoirs**, ~11 annual cycles (~583 records), **~3 release episodes**, closed loop after April 2026. Pitfalls and the explicit guardrails against them:

| Pitfall | Guardrail |
| --- | --- |
| Overfitting with high-capacity nets | Prefer simple/physics-informed: monotone rating curve, mass-balance forecaster, degree-day melt. Add capacity **only when walk-forward skill earns it**. The estimation bridge is a smoother, not a neural net. |
| Only 3 reservoirs (low spatial diversity) | **Pool across reservoirs** on `pct_filled` (size-comparable); reservoir-specific *features* differentiate; per-reservoir bias terms only if justified |
| Cold-start (new reservoir, no history) | DEM-prior rating curve + pooled forecaster + static features until local history accrues |
| Optimistic CV / leakage | **Leave-one-season-out + expanding-window walk-forward** only; time-based splits; point-in-time ABT (FR-ABT-3) forbids future leakage; per-regime metric breakout |
| Over-trusting point estimates | **Conformal intervals** (finite-sample) over parametric Gaussian; report coverage, not just MAE |
| Rare/imbalanced release events (~3) | Class weighting + threshold tuning; **PR metrics not ROC**; weak labels treated as noisy; backtest + case studies, not a claimed false-negative rate |
| Train/serve skew (observed vs forecast precip; bulletin vs SAR state) | Train on **GFS reforecasts** and **SAR-derived state** — both skew sources structurally closed |
| Sedimentation aging the curve | Dated/versioned curves; periodic re-fit from fresh matched pairs; flag capacity drift |
| Closed loop → no corrective feedback | Rating curve + SAR extraction are highest-risk; lock accuracy by one-time rigorous backtest; production monitoring is internal-consistency/drift only |

---

## 6. MLflow project structure & registry / promotion flow

### 6.1 Repository layout (`pipelines/ml/`)
```
pipelines/ml/
  pyproject.toml            # uv-managed deps for the ML track
  conf/                     # hydra/yaml: tolerances, horizons, CV folds, thresholds
  abt/                      # ABT + ForecastForcing readers (contract v2 bound), pandera schema
  groundtruth/              # FR-GT: nearest-match, indirect validation, GroundTruthMatch writer
  rating_curve/             # FR-GT-4: empirical fit, DEM blend, RatingCurve writer
  extraction_harness/       # FR-GT-5: per-candidate co-fit + per-regime selection
  weak_labels/              # FR-GT-6: weak-label set emitter
  estimation/               # FR-ML-1: curve inference (estimation bridge)
  forecasting/              # FR-ML-2: pooled Δ-fill GBR + conformal
  release_risk/             # FR-ML-3: trajectory→probability→level→lead time→factors
  backtest/                 # walk-forward harness, AC-5 episode backtest (NFR-TEST-3)
  monitoring/               # FR-ML-6: drift + internal-consistency
  inference/                # the interface the API calls (§9.3)
  flows/                    # Prefect 2 flows: calibrate, train, infer, backtest, monitor
  tests/                    # unit + integration (NFR-TEST-2)
```

### 6.2 MLflow experiments (one per stage)
- `rating-curve-calibration` — per-reservoir curve fits, fit metrics, AC-2 gate status.
- `extraction-harness` — every `(extractor + co-fit curve)` candidate, per-regime fill-% MAE.
- `forecast-pooled-deltafill` — pooled GBR runs, baselines, walk-forward skill, conformal coverage.
- `release-risk-backtest` — episode backtests, PR/lead-time/calibration, case studies.

Each run logs: `abt_version` (data snapshot), params, `contract_version`, CV fold config, the metric table, and artifacts (curve, model, conformal residuals, reliability plots).

### 6.3 Registered models & promotion
Registered models: `rating_curve` (per-reservoir or one multi-output), `water_extractor` (the selected pipeline pointer, co-owned with RS), `forecaster_pooled`, `release_risk_layer`.

Stages: **None → Staging → Production → Archived.** Promotion rules:
- `rating_curve` → Production requires AC-2 / NFR-ACC-1 pass (fill-% MAE ≤ tolerance) on walk-forward, per-reservoir.
- `water_extractor` → Production requires winning the per-regime harness AND (for U-Net) beating the incumbent.
- `forecaster_pooled` → Production requires beating persistence **and** Normal-Storage climatology (NFR-ACC-2) with calibrated conformal coverage.
- `release_risk_layer` → promoted on a passing backtest + documented case studies (AC-5); never gated on a live recall number.

Promotion is **chained**: a forecaster cannot be Production unless the rating curve it depends on is Production (FR-GT-7).

### 6.4 Retraining triggers & drift (FR-ML-6)
Closed loop ⇒ **no live ground truth**, so "validation" in production = internal-consistency & drift:
- **Triggers:** scheduled per-season retrain as each monsoon accrues (especially near-FRL obs); manual on contract bump; drift-threshold breach.
- **Drift / internal-consistency monitors (surfaced to admins):** SAR-derived state vs forecast residuals; extraction-confidence trend; feature drift (forcing distribution shift); physically-implausible jumps; conformal-coverage drift. No live ground-truth comparison is possible.

---

## 7. Interfaces & contracts we expose

### 7.1 Model artifact signatures (MLflow `pyfunc`)
- **`rating_curve`** — input: `{reservoir_id, surface_area_km2}` → output: `{volume_bcm, level_m, pct_filled, is_extrapolated, curve_version}`.
- **`forecaster_pooled`** — input: ABT row(s) for `(reservoir_id, date)` + joined `ForecastForcing` rows for horizons 1–14 → output per horizon: `{horizon, pred_pct_filled, pred_level_m, pred_volume_bcm, lower, upper, model_version}`.
- **`release_risk_layer`** — input: the forecast trajectory + intervals + reservoir thresholds + rule curve → output: `{release_probability, risk_level, estimated_lead_time_days, contributing_factors[], model_version}`.

### 7.2 Persisted output schemas (DB-owned entities we write)
- **`RatingCurve`** — `reservoir_id, version, fit_type='blended', curve_points/params (area↔storage(BCM)↔level(m)), frl/capacity anchors, observed_range, extrapolated_range, dem_epoch_waterline, fit_metrics, created_at`.
- **`GroundTruthMatch`** — `reservoir_id, gt_date, scene_id, time_gap_days, extracted_area, area_confidence, extraction_method/version, derived_volume, derived_level, residual_vs_ground_truth`.
- **`Prediction`** — `reservoir_id, run_timestamp, horizon_date, predicted level/volume/pct_filled, interval (lower/upper), model_version, abt_version`.
- **`ReleaseRisk`** — `reservoir_id, run_timestamp, release_probability, risk_level (Low/Watch/Warning/Imminent), estimated_lead_time_days, contributing_factors, model_version`.

### 7.3 Inference interface the API calls
A single callable façade `run_inference(reservoir_id, as_of_date) -> {estimation, forecast[1..14], release_risk}` that (a) loads Production model versions from the MLflow registry by URI, (b) reads the latest ABT + `ForecastForcing` rows point-in-time, (c) returns the three payloads above and persists `Prediction`/`ReleaseRisk` with `model_version` + `abt_version`. Invoked by the Prefect `infer` flow on every new acquisition (FR-ML-5) and callable on demand by the API.

### 7.4 MLflow model URIs (consumed by inference/API)
`models:/rating_curve/Production`, `models:/forecaster_pooled/Production`, `models:/release_risk_layer/Production`, `models:/water_extractor/Production`.

---

## 8. Library choices

| Need | Library | Rationale |
| --- | --- | --- |
| Env/packaging | **uv** | mandated; reproducible lockfile (NFR-MNT-1) |
| Tracking/registry | **MLflow** | mandated (FR-ML-4); pyfunc artifacts, registry, versioning |
| Orchestration | **Prefect 2** | mandated; flows for calibrate/train/infer/backtest/monitor |
| Dataframes | **pandas** (+ pyarrow) | ABT is modest size |
| Rating curve | **scikit-learn** `IsotonicRegression` / **scipy** monotone spline (`PCHIP`) | monotone, low-dimensional, no overfit |
| DEM flood geometry | **numpy/rasterio/xarray** | integrate area(elev)→volume above waterline |
| Forecaster | **LightGBM** (regularized GBR), monotone constraints | small-data-robust, fast, explainable |
| Conformal intervals | **MAPIE** (or hand-rolled split-conformal) | finite-sample calibrated intervals |
| Clustering (harness eval refs) | **scikit-learn** (KMeans/GMM), **scikit-image** (Otsu) | harness candidates' metrics; extraction *run* by RS |
| Explainability | **SHAP** (tree) for forecaster factor attribution | contributing factors (FR-ML-3) |
| Calibration | **scikit-learn** isotonic/Platt; sklearn reliability | release-risk calibration |
| Data validation | **pandera** (+ Great Expectations at pipeline edge) | ABT schema/range/null checks (NFR-TEST-1) |
| Testing | **pytest** | unit + integration (NFR-TEST-2) |

---

## 9. Testing & validation

- **CV strategy:** expanding-window walk-forward + **leave-one-season-out**, per-regime metric breakout (monsoon / winter-ice / wind-roughened). Strictly time-based; point-in-time ABT prevents leakage.
- **Baselines:** persistence + Normal-Storage climatology (forecaster must beat both — AC-4 / NFR-ACC-2).
- **Backtest (NFR-TEST-3 / AC-5):** one-time rigorous walk-forward over the ~11-year record; end-to-end backtest against ≥1 known near-FRL/release episode in the CI acceptance suite. Reports estimation MAE, forecast skill, release recall/precision/lead-time/calibration (PR-based), plus illustrative case studies.
- **Unit/integration (NFR-TEST-2):** rating-curve/estimation logic, ABT reader (contract v2 conformance), conformal coverage, release-risk thresholding, inference façade. CI runs all on every change (AC-12).
- **Gate wiring:** AC-2 (rating curve) → AC-3 (estimation) → AC-4 (forecast) → AC-5 (release-risk), each blocking promotion of the next.

---

## 10. Task breakdown (sequenced)

| ID | Task | Acceptance check |
| --- | --- | --- |
| **T-01** | ABT + `ForecastForcing` reader bound to `contract_version: 2`; pandera schema; stub-row filter | Reads real + stub ABT; rejects schema drift; unit tests green |
| **T-02** | Temporal nearest-match (FR-GT-1) → write `GroundTruthMatch` with `time_gap_days`; reject > ±N | Every bulletin matched or rejected with recorded gap; idempotent upsert |
| **T-03** | Indirect validation (FR-GT-3): area→derived storage/level, store `residual_vs_ground_truth` | Residuals computed per pair; persisted |
| **T-04** | Empirical monotone rating-curve fit (FR-GT-4), confidence/gap-weighted, FRL/capacity-anchored | Monotone fit; observed range flagged; fit metrics logged to MLflow |
| **T-05** | DEM-prior flood geometry + **blend** ([ADR-0004](../adr/0004-blended-rating-curve-dem-empirical.md)); persist `RatingCurve` (`blended`, waterline, ranges) | Blended curve persisted; overlap-divergence metric within tolerance or flagged |
| **T-06** | **Extraction-harness** (FR-GT-5 / [ADR-0007](../adr/0007-water-extraction-harness.md)): per-candidate co-fit curve, per-regime fill-% MAE selection | Winner selected on robust per-regime metric; all candidates in MLflow; pointer registered |
| **T-07** | AC-2 gate (FR-GT-7): fill-% MAE vs NFR-ACC-1; publish `gt_gate_status` | Gate computed per-reservoir + fleet; blocks downstream promotion |
| **T-08** | Weak-label set emitter (FR-GT-6) for U-Net | Versioned label artifact from low-residual/high-confidence pairs |
| **T-09** | Estimation bridge (FR-ML-1): curve inference + `is_extrapolated`; feed ABT/forecaster init | Calibrated volume/level/pct_filled per `Observation`; AC-3 holds |
| **T-10** | Forecaster (FR-ML-2 / [ADR-0006](../adr/0006-forecaster-pooled-delta-fill-conformal.md)): pooled Δ-fill GBR, direct multi-horizon, GFS-reforecast + SAR-state training, mass-balance term | Trains on reforecasts; walk-forward beats persistence + climatology (AC-4) |
| **T-11** | Conformal intervals (split/walk-forward); coverage report | PICP near nominal; intervals widen between obs dates |
| **T-12** | Release-risk layer (FR-ML-3): episode labels, trajectory→probability→level→lead time, SHAP factors, calibration | Risk level + lead time + factors produced; PR/lead-time/calibration on backtest |
| **T-13** | Backtest harness (NFR-TEST-3 / AC-5): walk-forward + known-episode E2E in CI | Episode backtest + case studies pass; AC-5 evidence produced |
| **T-14** | MLflow registry + chained promotion rules; model URIs | Promotion blocked unless upstream gate passes; URIs resolvable |
| **T-15** | Inference façade (§7.3) + Prefect `infer` flow (FR-ML-5); persist `Prediction`/`ReleaseRisk` | On new acquisition, three payloads persisted with model + abt versions |
| **T-16** | Drift / internal-consistency monitoring (FR-ML-6); retraining triggers | Monitors surface SAR-vs-forecast residuals, confidence trend, feature drift, implausible jumps |

Sequencing: T-01 → (T-02→T-03→T-04→T-05→T-06→T-07) gate → T-08/T-09 → T-10→T-11 → T-12→T-13 → T-14→T-15→T-16. The Stage-A gate (T-07) blocks production promotion of T-10+.

---

## 11. Mapping to acceptance criteria

| AC | Owned deliverable |
| --- | --- |
| **AC-2 (foundational gate)** | T-02…T-07: nearest-match, indirect validation, blended rating curve, extraction selection, NFR-ACC-1 gate. Selected extractor + per-reservoir curve validated & versioned. |
| **AC-3** | T-09 estimation meets NFR-ACC-1 on held-out validation. |
| **AC-4** | T-10/T-11 forecaster beats persistence + climatology (NFR-ACC-2) with published conformal uncertainty. |
| **AC-5 (primary)** | T-12/T-13 release-risk on held-out near-FRL episodes — recall at min lead time, calibrated probabilities, contributing factors, **plus case studies** ([ADR-0001](../adr/0001-release-risk-is-a-layer-not-a-validated-classifier.md)). Backtest numbers, not live. |
| AC-10 (support) | We consume the point-in-time ABT and record `abt_version` on every run. |
| AC-12 (support) | Backtest + data-validation in CI. |

---

## 12. Risks & open decisions

### Risks
- **Closed loop:** rating curve + SAR extraction carry the whole system with no production corrective feedback. Mitigation: rigorous one-time backtest, drift monitoring, conservative extrapolation flags.
- **~3 release episodes:** release-risk cannot be a validated classifier. Mitigation: transparent layer + PR metrics + case studies; never claim a live false-negative rate.
- **DEM-epoch waterline estimation** adds per-reservoir error in the near-FRL release zone (exactly where risk lives). Mitigation: record waterline + its error with the curve; DEM contributes shape not offset.
- **Normal-Storage proxy** may understate deliberate pre-monsoon flood-cushion drawdown ([ADR-0002](../adr/0002-normal-storage-as-rule-curve-proxy.md)) → episode labels may differ from operator intent. Mitigation: weak-label treatment; flagged; v2 official rule curves.
- **GFS reforecast archive coverage** (≥ 2015-07) must actually back the training window, or train/serve skew returns. Dependency on Data Engineering's `ForecastForcing` build.

### Open decisions affecting other tracks (esp. what we need in the ABT)
1. **Evaporation / outflow term:** §8.3 wants evaporation as an outflow term where estimable. **Needed in ABT/CatchmentForcing:** a catchment/lake-surface temperature or pan-evaporation proxy (ERA5-Land), currently not in the contract. → request to DE (would be a `contract_version` bump).
2. **`time_gap_days` / `area_confidence` at the matched-pair grain:** confirm whether DE surfaces these on the ABT or we recompute from `GroundTruthMatch`. The ABT has `days_since_acquisition` but not the matched gap.
3. **Final NFR-ACC-1 tolerance** (5% vs 10% fill-% MAE) must be fixed with the DS/PM before AC-2 can pass — gates all downstream promotion.
4. **Release-threshold bands per reservoir** (Watch/Warning/Imminent level/fill-% cutoffs) — owned by DB/Reservoir config; we need them frozen to compute risk levels and lead time.
5. **Rating-curve grain:** one multi-output registered model vs per-reservoir models — confirm with API how it wants to resolve curve versions at serve time.
6. **DEM hypsometric `area(elev)` shape ownership:** confirm RS/DEM tooling emits the flooded-DEM shape artifact we blend, vs we compute it from the raw DEM (affects T-05 scope).
