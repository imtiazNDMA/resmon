> **STATUS: PROPOSAL (2026-06-30) — not adopted.** Captured from a stray temp file during
> the 2026-07-03 remediation; contradicts the current ADR-0004 blended-rating-curve decision
> and must be explicitly accepted or rejected.

# Replan — Phase 1: State Estimation from Imagery + Catchment Forcings

**Status:** Proposed · **Date:** 2026-06-30 · **Author:** RS engineering
**Supersedes for Phase 1:** the forecast + release-risk emphasis in `README.md` / `requirements.md`.
**Touches ADRs:** 0004 (blended rating curve), 0005 (closed loop), 0007 (extraction harness).

---

## 1. Phase-1 goal (re-scoped)

> Given a Sentinel-1 SAR scene (and catchment forcings) for a reservoir on **any** date,
> output **`{level (m), live storage (BCM), pct_filled}`** with **calibrated uncertainty**.

**Explicitly out of scope for Phase 1** (deferred, not deleted):

- 1–14 day **forecasting** (pooled Δ-fill, ADR-0006).
- **Release-risk** levels Low/Watch/Warning/Imminent (ADR-0001).
- Episode reconstruction / backtest of release episodes.

These remain valid future phases; Phase 1 builds the **estimation bridge** they all depend on
(CONTEXT.md: "the sole production path to storage once bulletins stop").

---

## 2. The estimator (decided)

A **Physics-Informed Neural Network (PINN)** is the **primary** area→state estimator,
**replacing** the standalone blended rating curve as the production mapping — but with the
reservoir geometry re-introduced as **hard physics constraints** in the loss, which is what
makes a neural net viable on a small dataset.

```
inputs  → { SAR water_area,
            antecedent_precip_index, degree_day_melt, snowmelt/SWE, temperature_2m,
            reservoir-geometry features (FRL, capacity@FRL, hypsometry descriptors),
            normalized fill = storage / live_capacity_FRL }
PINN    → { level_m, live_storage_BCM, pct_filled }  (+ conformal interval)
```

**Pooled across all 3 reservoirs** (Gobind Sagar, Pong, Thein) — one network trained on the
full ~580-record corpus, conditioned on per-reservoir geometry features so it learns a
*transferable* area→volume structure rather than three data-starved per-dam fits.

### 2.1 Loss (physics is non-negotiable)

```
loss = data_fit(level, volume, pct_filled)
     + λ1 · monotonicity        # ∂level/∂area ≥ 0, ∂volume/∂area ≥ 0, ∂volume/∂level ≥ 0
     + λ2 · hypsometric         # dV/dh ≈ A(h): volume–level–area triple obeys basin geometry
     + λ3 · DEM_anchor          # pin outputs to DEM hypsometry in the observed-max → FRL band
     + λ4 · mass_balance        # ΔS between successive dates consistent with precip+melt−outflow
```

- **λ1 Monotonicity** — water cannot rise in level/volume while area falls (per reservoir).
  Stops the net learning non-physical wiggles to chase noise.
- **λ2 Hypsometric consistency** — ties the three outputs together through basin geometry;
  this is the soft prior that *replaces* the rating curve's built-in smoothness.
- **λ3 DEM anchor (critical)** — the bulletin history only reaches the *observed* fill
  maximum. The flood-relevant band (observed-max → FRL) has **zero training labels**, so the
  loss anchors the net to **Copernicus GLO-30 DEM hypsometry** there (ADR-0004). Without this,
  the net extrapolates unpredictably in exactly the zone the platform exists to watch.
- **λ4 Mass balance** — successive-date storage change should track
  `inflow(precip, melt) − outflow`. This is where temperature/precip/snowmelt earn an *honest*
  gradient signal (driving change-over-time) rather than acting as seasonal shortcuts in a
  static map.

> The blended rating curve is **retained as the baseline to beat** and as the source of the
> DEM-anchor term. The PINN must demonstrably out-perform it on the holdout to justify its
> complexity; otherwise we fall back to the curve (ADR-0004 stays the safety net).

---

## 3. Critique of the plan (caveats · upsides · downsides · improvements)

### 3.1 Upsides
- **Right scope cut.** State estimation is the foundational layer; deferring forecast/alert
  focuses effort on the component everything else inherits error from (ADR-0005).
- **Forcings add real value in the hard regimes.** Bhakra/Pong/Thein sit in Himalayan
  foothills; winter ice / snow cover degrade SAR water detection (ADR-0007 disqualifies methods
  that "collapse on winter ice"). Met forcings give the estimator an independent signal exactly
  when SAR area is least trustworthy.
- **A PINN is a defensible vehicle** *if* physics regularizes it — which is the design above.

### 3.2 Caveats & downsides (and the mitigation baked into §2)
| Risk | Why it bites | Mitigation in this plan |
|---|---|---|
| **Tiny dataset** (~194 weekly rows/reservoir, ~580 total) | An unconstrained NN overfits and learns seasonality, not geometry | Hard physics constraints (§2.1) + pooling + conformal UQ |
| **No near-FRL labels** | History stops at observed max; flood zone is unobserved | **DEM-anchor (λ3)** pins geometry observed-max → FRL |
| **Temporal mismatch** | Bulletins weekly; S1 revisit ~6–12 d (worse post-S1B loss). Scene date ≠ bulletin date → the level *moved* in between | Nearest-scene matcher with tolerance window; mass-balance term (λ4) corrects for drift days |
| **Garbage-in (area error)** | SAR extraction error is the dominant term (ADR-0007); no net repairs a noisy input | Carry `area_confidence` as a feature + sample weight; quality-gate frozen/wind scenes |
| **Snowmelt not wired** | `forcing.py` hardcodes `snow_cover_area=0.0`, `swe=0.0`, `region={}` | Phase-1 must *build* catchment delineation + a real snow product (see §4) |
| **Train/serve skew** | ADR-0005: training on raw bulletin values then serving on SAR-derived state silently degrades | Train against the **SAR-derived chain**, not raw bulletins; replay the production path in CV |
| **Met forcings ≠ static geometry** | Physically, area→volume is geometry; forcings drive *dynamics* | Forcings enter via the **mass-balance term**, not as free static inputs |
| **Closed loop, no live correction** | Production never sees bulletins again (ADR-0005); errors are uncorrected | Accuracy fixed by walk-forward backtest; ship internal-consistency/drift monitors |

### 3.3 How to make it effective (improvements)
1. **Densify the area series** — there are more usable SAR scenes than bulletin dates; build a
   dense `area(t)` series and interpolate, rather than only training on bulletin-day matches.
2. **Confidence-weighted training** — weight each sample by `area_confidence` and downweight
   monsoon-turbid / winter-ice scenes; report metrics broken out by season/regime (ADR-0007),
   prefer the *robust* model not the lowest-mean one.
3. **Honest cross-validation** — **leave-one-season-out + walk-forward** only; never random
   splits (temporal leakage inflates skill).
4. **Calibrated uncertainty** — conformal intervals on the outputs so future phases inherit
   trustworthy bands (consistent with ADR-0006's conformal forecaster).
5. **Ablations** — log a rating-curve baseline, a no-physics net, and the full PINN in MLflow;
   keep the model pluggable & versioned (FR-RS-2) so promotion is an earned upgrade.
6. **Design toward the mass-balance dynamics** — the λ4 term is the seed of the deferred
   forecaster; keep its formulation forecast-compatible so Phase 2 extends rather than rewrites.

---

## 4. Data & infrastructure gaps to close in Phase 1

These are *missing today* and are real tasks, not assumptions:

1. **Catchment delineation per dam** — replace `region = {}` in `forcing.py` with persisted
   catchment polygons (HydroSHEDS/HydroBASINS or DEM-derived watershed above each dam).
2. **Real snow product** — wire `snow_cover_area` / `swe` from MODIS (MOD10A1) or
   Sentinel-2 snow cover + ERA5-Land snow variables; current values are placeholder `0.0`.
3. **SAR ↔ bulletin matcher** — nearest-available-scene join with a configurable tolerance
   window and recorded date-offset (feeds the mass-balance correction).
4. **Area time series at scene cadence** — persist extracted `water_area` + `area_confidence`
   for every usable scene, not just bulletin dates.
5. **DEM hypsometry export** — make the `area(elev)` / `volume(elev)` curve from ADR-0004
   available as the λ3 anchor target (already produced; expose to the trainer).

---

## 5. Architecture placement (where the code lands)

- `pipelines/remote_sensing/` — unchanged role: SAR → `water_area` + `area_confidence`
  (ADR-0007 harness stays the upstream).
- `pipelines/data_engineering/forcing.py` — **extended**: real catchment polygons + snow
  product; emit the forcing features the PINN consumes.
- `pipelines/ml/` — **new `estimation` model**: the PINN trainer/predictor sits alongside
  `curve.py` (kept as baseline) and `estimation.py`; `forecaster.py`/`release*.py` go dormant
  for Phase 1.
- `core/` — schema additions for PINN outputs + conformal intervals + per-scene area series.
- Frozen inter-pipeline contract (ADR-0003) — the observation/ABT contract may need a versioned
  bump to carry scene-cadence area + forcing features; treat as a contract change, not ad hoc.

---

## 6. Phase-1 acceptance criteria

1. **Accuracy** — pooled PINN beats the blended-rating-curve baseline on derived **fill-% MAE**,
   walk-forward / leave-one-season-out, across all three reservoirs and broken out by season.
2. **Physical validity** — monotonic outputs; near-FRL band matches DEM hypsometry within
   tolerance (no runaway extrapolation on held-out high-fill checks).
3. **Calibration** — conformal intervals achieve nominal coverage on the holdout.
4. **Robustness** — no regime (monsoon / winter-ice / wind-roughened) collapses; degraded
   scenes are flagged via `area_confidence`, not silently trusted.
5. **Closed-loop ready** — trained and evaluated on the **SAR-derived chain**, no raw-bulletin
   leakage; internal-consistency/drift monitors stubbed (ADR-0005).

---

## 7. Open questions for follow-up

- Tolerance window for the SAR↔bulletin matcher (days), and how to weight large offsets.
- Snow product choice (MODIS vs S2 vs ERA5-Land SWE) and catchment source (HydroBASINS vs DEM).
- PINN architecture/size budget given ~580 rows (lean MLP + physics is likely enough).
- Whether the contract bump (§5) is in-scope for Phase 1 or a precursor task.
