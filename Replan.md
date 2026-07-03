# Replan — Phase 1: Reservoir State Estimation from SAR + Catchment Forcings

**Status:** ADOPTED (2026-07-03) · **Decision:** forecast + release-risk are **out of scope for Phase 1**
**Refines:** `docs/plans/08-replan-proposal-pinn.md` (the PINN proposal) with the resequencing and
constraint fixes from the 2026-07-03 review · **Touches ADRs:** 0004, 0005, 0006 (dormant), 0007
**Supersedes for Phase 1:** the forecast/release-risk emphasis in `README.md` / `requirements.md`.

---

## 1. Goal

> Given a Sentinel-1 SAR scene (or the nearest available one) and catchment met forcings
> (temperature, precipitation, snowmelt) for a reservoir on **any** date, output
> **`{level_m, live_storage_bcm, pct_filled}`** with **calibrated uncertainty**.

The historical bulletins (2015–2026, ~194 weekly records × 3 reservoirs) are the **training
labels**: we backfill SAR imagery for the corresponding (or nearest) dates, extract water area,
and learn the relationship `area + forcings → state`. Once established, production runs on
imagery + forcings alone — the closed loop of ADR-0005 (bulletins stop; SAR continues).

**Explicitly out of scope for Phase 1** (deferred, not deleted — code goes dormant behind flags):
1–14 day forecasting (ADR-0006), release-risk levels & episode backtesting (ADR-0001), alerting.

---

## 2. Where the repo stands today (post-remediation, commit `08f0a6b`)

| Capability | State |
|---|---|
| Adaptive per-scene water extraction (histogram Otsu, abstain gate, orbit/coverage enforcement) | ✅ built, **never run on real scenes** |
| Catchment polygons (HydroBASINS upstream traversal) | ✅ built, needs live GEE execution + eyeball |
| SAR↔bulletin matcher (`ground_truth_match`, ±5 d, stub-excluded) | ✅ built |
| Scene-cadence `observation` persistence with `area_confidence` + provenance | ✅ schema + pipeline ready |
| ERA5-Land forcing ingest (latency-shifted, unit-correct, NULL-not-zero) | ✅ built, fixture-fed (needs live GEE) |
| Snow product (`snow_cover_area`, `swe`) | ❌ placeholder NULL — must be built |
| DEM hypsometry (GLO-30 area/volume–elevation curve) | ❌ not built |
| Blended rating curve (empirical + DEM above observed max, ADR-0004) | ❌ only the empirical linear half exists |
| Historical SAR backfill (2015→present, all scenes) | ❌ not run |
| MLflow model registry | ❌ deployed but unused |

Phase 1 is therefore mostly **execution + two missing data products + the estimator study**, not
new plumbing.

---

## 3. The plan, in three stages

### Stage 1 — Build the matched historical dataset (the real work)

1. **Scene inventory recon (do this first, it sizes everything).** For each reservoir, query the
   S1 GRD archive over the AOI: scenes per year, per orbit/pass, coverage gaps. Expect ~6–12 day
   cadence 2016–2021 (S1A+S1B), degrading to ~12–24 days after the S1B failure (Dec 2021),
   recovering with S1C (2025). This determines match tolerance, seasonal coverage, and how many
   of the ~580 bulletins actually get a usable pair.
2. **Historical extraction backfill.** Run the (now-correct) extraction chain over every usable
   scene 2015→present: adaptive threshold, abstain on unimodal/wind-merged scenes, per-scene
   `area_confidence`, orbit-consistent series. Batch with GEE quota awareness; idempotent;
   `pipeline_run`-tracked. Output: a dense `area(t)` series per reservoir — **more sample dates
   than bulletins**, which is the point.
3. **Match to bulletins.** Reuse `ground_truth_match` (nearest scene, recorded `date_offset`).
   Tolerance is seasonal: tight during monsoon (level moves % per day), looser in dry season.
   Weight training pairs by both `area_confidence` and `|date_offset|`.
4. **Forcings, live.** Execute the ERA5-Land ingest against the real catchments; **build the snow
   product**: MODIS MOD10A1 fractional snow-cover area aggregated over the catchment +
   ERA5-Land SWE as the water-equivalent proxy (coarse at 9 km in complex terrain — treat as an
   index, not truth). Degree-day melt from the already-fixed temperature path.
5. **DEM hypsometry export.** GLO-30 `area(h)` / `V(h)` per reservoir. **Honest caveat:** the
   TanDEM-X acquisition (~2011–2015) saw water in the pool, so the DEM is only informative
   **above the DEM-epoch waterline** (`rating_curve.dem_epoch_waterline_m` already models this).
   Below it there is no bathymetry — the empirical fit owns that zone.
6. **Independent validation set (new, important).** Satellite altimetry gives **direct level
   measurements** with no dependence on our SAR chain: ICESat-2 ATL13 inland-water crossings and
   Sentinel-3/Jason tracks (via DAHITI / Hydroweb if available for Gobind Sagar / Pong / Thein).
   Even a few dozen crossing dates per reservoir is a truly independent check on `level_m` that
   neither the bulletins nor our own extraction can contaminate.

### Stage 2 — Establish the relationship (a fair three-way fight, not a foregone conclusion)

Train and compare **three model classes** under identical evaluation:

- **A. Blended monotone rating curve (baseline, per reservoir).** Shape-constrained fit
  (monotone spline / isotonic) on matched pairs, blended into DEM hypsometry above the observed
  maximum (ADR-0004 as designed). Satisfies monotonicity + hypsometric consistency + DEM anchor
  **by construction**, ~10 parameters. *This must be built regardless — it is the PINN's anchor
  target and the promotion baseline.*
- **B. Curve + state-space filter.** The curve as observation operator inside a Kalman-style
  filter/smoother; forcings drive the process model (storage dynamics). This is the natural
  vehicle for "forcings help when SAR is unreliable" — ice/wind scenes get downweighted by their
  observation noise (from `area_confidence`) and the state coasts on dynamics.
- **C. Physics-constrained NN (the PINN).** Pooled across reservoirs, conditioned on geometry
  features, with the loss from the proposal — **amended**:
  - λ1 monotonicity, λ2 hypsometric consistency, λ3 DEM anchor: unchanged.
  - λ4 mass balance **must be the inequality form**: `ΔS ≤ inflow(precip, melt) + ε` — storage
    cannot rise by more than the catchment supplied. The equality form in the original proposal
    requires **outflow, which is unobserved** (releases are the thing the platform ultimately
    watches) and is therefore circular. One-sided mass balance is valid without knowing outflow.

**Evaluation protocol (non-negotiable):** walk-forward + leave-one-season-out only; never random
splits. Metrics broken out by season/regime (monsoon, winter-ice, wind-flagged) and per
reservoir. Conformal intervals with coverage (PICP) reported per regime. Scored against
held-out bulletins **and** the altimetry set. All runs logged to MLflow (curve baseline,
no-physics ablation, full physics) — promotion to production is an **earned upgrade**: C must
beat A on the holdout by a margin that survives the regime breakout, or A/B ships.

### Stage 3 — Production serving

`estimation.py` serves the promoted model: latest usable scene → area + confidence → state +
conformal interval → persisted (schema already carries `derived_storage`/`derived_level`;
interval columns are a contract-versioned addition). API/dashboard show **level, storage, fill
with uncertainty bands + data-age**; forecast panel and risk badge are feature-flagged off (code
dormant, not deleted). Internal-consistency/drift monitors (ADR-0005): area↔state residual
tracking, so a drifting extractor is caught without ground truth.

---

## 4. Assessment (RS scientist + engineer view)

### Pluses
- **Right foundation.** Every downstream capability inherits estimation error; fixing the
  foundation first is what the 2026-07-03 review demanded. The closed-loop framing is honest:
  bulletins are a bootstrap, SAR+forcings are the production diet.
- **The historical-backfill idea is the highest-value move available.** ~11 years of labels ×
  scene-cadence areas is the only way to get regime coverage (monsoon, ice, wind) into training
  — and it exercises the extraction chain at scale before anyone trusts it.
- **Forcings have a real job** — but only in the dynamics (Stage 2B/λ4), where they carry
  information SAR lacks exactly when SAR degrades.

### Caveats
- **Scene–bulletin temporal mismatch is the dominant label noise.** During monsoon fill, ±3 days
  can be several % of live storage. Mitigations: seasonal tolerance, offset weighting, and the
  dynamics term absorbing drift days. The recon (Stage 1.1) tells us how bad this actually is.
- **The static mapping is geometry; don't let forcings fake it.** If temperature/precip enter as
  free static covariates, the model learns "July = full" and fails precisely in anomalous years
  — the ones a disaster platform exists for. Forcings enter through dynamics only.
- **DEM blindness below the epoch waterline** — the anchor only constrains the upper band; the
  empirical fit owns the rest. Both zones must be flagged in `is_extrapolated`-style metadata.
- **ERA5-Land SWE at 9 km in the Himalaya is an index, not a measurement.** Treat snow features
  as weak signals; never let the model lean on them harder than their information content.

### Downsides
- **~580 labeled pairs is small for any NN**, physics or not. Expect the curve (+filter) to be
  hard to beat; that is a fine outcome — the study still yields the validated estimator.
- **Pooling across 3 dams cannot demonstrate transferability** (no held-out reservoir; geometry
  features take only 3 values, so the net can memorize identity). Pooling is a regularizer here,
  not a generalization claim — say so in any write-up.
- **GEE execution cost/quota** for ~1,500–3,000 historical extractions: needs batching, caching,
  and restartability (the idempotent machinery from the remediation makes this tractable).
- **λ-weight tuning appetite**: four penalty weights on a tiny dataset invites "physics theater"
  (constraints satisfied where evaluated, nonsense elsewhere). The no-physics ablation and the
  altimetry check are the guards.

### How to make it effective
1. **Recon before commitment** — the scene inventory (Stage 1.1) is one day of work and sizes
   the entire phase.
2. **Curve first, network second** — A is on the critical path regardless (anchor + baseline);
   building it first de-risks everything and may end the story.
3. **Inequality mass balance** — resolves the outflow circularity; keep the formulation
   forecast-compatible so a future Phase 2 extends rather than rewrites.
4. **Altimetry as the referee** — the only validation source independent of both bulletins and
   our own SAR chain.
5. **Regime-stratified everything** — selection by worst-regime performance (robustness), not
   best mean (ADR-0007's principle, now applied to the estimator).
6. **Confidence-weighted training + abstain propagation** — a scene the extractor abstained on
   never becomes a training pair; low-confidence scenes are downweighted, not laundered.

---

## 5. Engineering changes (full-stack)

- **Contract bump (v4):** conformal interval columns on derived state; `date_offset` +
  match-quality on training pairs; snow feature columns documented as index-grade. Follow the
  frozen-contract discipline (`docs/contracts/observation-and-abt.md` + parity test).
- **`pipelines/ml/`:** new `estimation_models/` (curve A, filter B, PINN C behind one interface);
  `curve.py` grows the DEM blend; `forecaster.py`, `release*.py`, `episodes.py` dormant behind a
  `PHASE1_ESTIMATION_ONLY` flag — **not deleted** (the replayed backtest built in the
  remediation is Phase-2 machinery we want back).
- **`pipelines/remote_sensing/`:** backfill driver (scene inventory → batched historical
  extraction → `observation` rows), resumable via `pipeline_run`.
- **`pipelines/data_engineering/forcing.py`:** MOD10A1 snow-cover aggregation + ERA5-Land SWE
  behind `DataAccessBackend`.
- **MLflow:** actually used — every Stage-2 run logged; promotion gate consumes the registry.
- **API/web:** status + timeseries + uncertainty bands stay; forecast/risk endpoints and UI
  panels feature-flagged off; OpenAPI reflects Phase-1 surface.
- **CI:** the Stage-2 evaluation harness runs as a gate on synthetic fixtures (machinery), with
  provenance stamps (`on_synthetic_data`) carried through — real-data gates run manually until
  live GEE is in CI reach.
- **Docs:** update `README.md` spine + `requirements.md`/`todos.md` scope notes; ADR-0006/0001
  marked dormant-not-dead; new ADR recording this decision and the A/B/C promotion protocol.

---

## 6. Phase-1 acceptance criteria

1. **Coverage:** historical backfill yields a matched dataset with quantified scene counts,
   offsets, and abstain rates per reservoir/season (recon numbers published in the repo).
2. **Accuracy:** the promoted estimator beats the blended-curve baseline on fill-% and level MAE
   under walk-forward + leave-one-season-out, per reservoir, with **no regime collapse**.
3. **Independence:** level estimates validated against altimetry crossings where available.
4. **Calibration:** conformal intervals achieve nominal coverage per regime on the holdout.
5. **Physical validity:** monotone outputs; near-FRL band within tolerance of DEM hypsometry;
   extrapolation zones flagged.
6. **Closed-loop ready:** trained/evaluated on the SAR-derived chain (no raw-bulletin leakage at
   serve time); drift monitors emitting.

## 7. Open questions

- Seasonal match-tolerance values (set after Stage-1.1 recon, not before).
- Altimetry availability for the three reservoirs (DAHITI/Hydroweb coverage check).
- Whether B (filter) and C (PINN) both get built or the filter is attempted only if A's
  ice/wind-regime residuals justify it.
- Contract-v4 timing: precursor task or landed with Stage 3.
