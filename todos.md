# Implementation TODOs — Reservoir Monitoring & Analytics Platform

Step-by-step build checklist, sequenced on the dependency spine in [docs/plans/00-master-implementation-plan.md](docs/plans/00-master-implementation-plan.md). Detail for each task lives in the domain plans (`docs/plans/01`–`07`) and the frozen contract (`docs/contracts/observation-and-abt.md`).

## Scope for v1 (read first)

- ✅ **No authentication / login** — the platform is open in v1. No users/roles tables, no JWT, no RBAC, no role-gated routes. *(Can be added later behind the API.)*
- ✅ **No alert / notification subsystem** — no `Alert` entity, no threshold-crossing alert generation, no acknowledgement/history, no push (email/SMS/webhook). **Release-risk is still computed, persisted (`ReleaseRisk`), served, and displayed** on the map/dashboard — only the reactive alerting layer is cut.
- **Resolved decisions:** AC-2 gate tolerance = **fill-% MAE ≤10%** to start (tighten later); ABT/forcing **`contract_version: 3`** adds an **evaporation** column (ERA5-Land) at P1.

**Legend:** `[ ]` todo · `→plan NN-Txx` source task · `(AC-n)` acceptance criterion · ⛔ gate.

---

## Phase 0 — Foundations (Infra + DB core)

*Goal: one-command bring-up, migrated schema, green CI. Unblocks everything.*

- [ ] Scaffold monorepo + `uv` workspace; `core/`, `db/`, `pipelines/`, `orchestration/`, `api/`, `web/`, `infra/`, `tests/` →01-T01
- [ ] `.gitattributes` LF enforcement + go-task/POSIX scripts (Windows host, run inside containers) →01
- [ ] Shared multi-stage `uv` Python base image →01-T05
- [ ] `docker-compose` (base/dev/prod): `postgres`+PostGIS, `mlflow`, `prefect-server`, `prefect-worker`, `api`, `web`, `pipeline-worker`, `proxy` (Caddy) →01-T10 (AC-8)
- [ ] `.env.example` + file-mounted secrets convention; wire `geeservice.json` as `GEE_SA_KEY_FILE` →01
- [ ] `DataAccessBackend` ABC + `GEEBackend` + `FixtureBackend` (the swappable GEE seam) →01-T12
- [ ] `core/` SQLAlchemy 2.x models + Pydantic v2 schemas mirroring the frozen contract →02-T01
- [ ] Alembic baseline migration →02
- [ ] Contract tests: `Observation`/`ABT`/`ForecastForcing` schema matches `contract_version` →01/02
- [ ] CI skeleton: ruff + mypy + lockfile check + pytest on ephemeral PostGIS →01-T20 (AC-12 partial)

**Exit:** `docker compose up` brings the stack up; migrations apply; CI green.

---

## Phase 1 — DB schema (no auth/alert tables)

*Goal: the canonical physical schema everything writes/reads.*

- [ ] `reservoir` (AOI + catchment geom SRID 4326, FRL, capacity, `release_thresholds` jsonb, rule-curve proxy, `orbit_relative`/`pass_direction`) →02-T02
- [ ] `reservoir_capacity_history` (sedimentation / time-varying capacity) →02
- [ ] `observation` (contract §1, incl. `extraction_method='stub'` support) →02-T03
- [ ] `ground_truth` (bulletin columns, `row_quality`) →02
- [ ] `ground_truth_match` (AC-2 evidence) →02-T04
- [ ] `rating_curve` (blended; observed/extrapolated ranges; `dem_epoch_waterline_m`) →02-T04
- [ ] `catchment_forcing` **+ `evaporation` column (contract v3)** →02 / contract bump
- [ ] `forecast_forcing` (horizon-keyed, contract §3) →02
- [ ] `analytical_base_table` + `abt_current` view (contract §2, versioned snapshot) →02-T05 (AC-10)
- [ ] `model_version`, `prediction`, `release_risk` (append-only) →02
- [ ] `pipeline_run` (observability/idempotency) →02
- [ ] ~~`app_user`/`role`/`user_role`~~ **descoped (no auth)**
- [ ] ~~`alert`~~ **descoped (no alert system)**

**Action:** bump `docs/contracts/observation-and-abt.md` to `contract_version: 3` (add `evaporation`), note in changelog, notify tracks.

**Exit:** all tables migrated; constraint/schema tests pass.

---

## Phase 2 — Data Engineering: bulletins → ABT (stub Observations)

*Goal: a populated, leakage-free ABT so ML + serving can start before real SAR.*

- [ ] Promote `pipelines/build_unified_dataset.py` cleaning/dedup/quarantine to `de/cleaning.py` →04-T02
- [ ] Bulletin bronze→silver ingest (`data/historical/reservoir_timeseries.csv`) →04-T02
- [ ] Generate **stub `Observation`** rows (invert rough bulletin curve) →04 / contract stub rule
- [ ] Fuse Observations ↔ ground-truth → `ground_truth_match` (nearest ±N, default ±5d) →04-T04
- [ ] Catchment delineation (HydroBASINS, MERIT `upa` validation, `pyflwdir`) →04-T06
- [ ] Hydromet ingest + catchment aggregation via `xee` (CHIRPS/IMERG/ERA5-Land/GLDAS/MODIS) incl. **evaporation** →04-T07
- [ ] `ForecastForcing` ingest (GFS `NOAA/GFS0P25`, point-in-time reforecasts; verify 2015+ archive) →04
- [ ] `build_abt` — point-in-time builder (IST/UTC alignment, `merge_asof`, versioned, quality/freshness flags) →04-T10 (AC-10)
- [ ] Data-validation suite (pandera/Great Expectations) wired into CI gate →04 (AC-12)
- [ ] Prefect flows + RS→DE→ML trigger chain →04

**Exit:** ABT v1 populated & leakage-tested; data-validation gate green.

---

## Phase 3 — Remote Sensing: real water extraction

*Goal: real `Observation` rows replace stubs.*

- [ ] GEE client wrapper over `DataAccessBackend` (no raw `ee.Initialize`) →03-T01
- [ ] AOI bootstrap from JRC GSW max-extent → versioned GeoJSON → PostGIS →03-T02
- [ ] Reservoir orbit/AOI config schema; **freeze relative orbit + pass per reservoir (D1)** →03-T03
- [ ] SAR preprocessing: calibration → speckle → **radiometric terrain flattening (γ⁰)** →03-T06
- [ ] **DEM-based layover/shadow masking** (steep-terrain critical) →03-T07
- [ ] `WaterExtractor` plugin ABC + registry; cold-start extractors (`otsu_vh`, `kmeans`, `gmm`) →03 / ADR-0007
- [ ] True-area via `ee.Image.pixelArea()`; per-area confidence (separability, compactness, layover fraction) →03
- [ ] DEM hypsometric-shape handoff for the blend →03 / ADR-0004
- [ ] Extraction harness: per-regime robust selection → MLflow-registered winner →03-T16 (AC-2 input)
- [ ] Emit real `Observation` rows; re-run DE ABT on real data →03

**Exit:** real Observations in DB; extraction method selected & registered.

---

## Phase 4 — Ground-truthing & blended rating curve ⛔ (AC-2 gate)

*Goal: prove SAR-derived storage reproduces known history within tolerance.*

- [ ] ABT reader (contract-bound) →05-T01
- [ ] Nearest-match `GroundTruthMatch` build →05-T02
- [ ] Empirical area↔storage↔level fit (anchored by FRL/capacity) →05-T04
- [ ] DEM-blended curve (empirical owns observed range; DEM near-FRL) →05-T05 / ADR-0004
- [ ] Extraction-method validation feeds harness selection →05-T06
- [ ] ⛔ **AC-2 acceptance gate**: fill-% MAE **≤10%** on matched set; curve versioned →05-T07 (AC-2)

**Exit:** AC-2 passes on **real (non-stub)** Observations. *Do not start Phase 5+ until green.*

---

## Phase 5 — Estimation & Forecasting

*Goal: the validated predictive engine.*

- [ ] Estimation bridge (area → storage/level via rating curve) wired into inference →05
- [ ] Pooled Δ-fill forecaster (1–14 day) with conformal intervals →05 / ADR-0006
- [ ] Persistence + climatology baselines →05
- [ ] Walk-forward / leave-one-season-out CV; skill-vs-baseline →05 (AC-4)
- [ ] Persist `Prediction` rows (intervals, `model_version`, `abt_version`) →05 (AC-3)

**Exit:** AC-3 (estimation) + AC-4 (forecast beats baseline) met.

---

## Phase 6 — Release-risk layer (compute + persist, no alerting)

*Goal: the user-facing risk indicator — transparent, not a classifier.*

- [ ] Release-risk layer: forecast trajectory vs FRL/threshold bands net of rule curve →05 / ADR-0001
- [ ] Risk levels (Low/Watch/Warning/Imminent), lead time, contributing factors →05
- [ ] Freeze per-reservoir release-threshold bands in reservoir config (D7) →02/05
- [ ] Persist `ReleaseRisk` rows →05
- [ ] Episode backtest (the ~3 historical release episodes) →05 (AC-5)
- [ ] ~~Alert generation / acknowledgement / audit~~ **descoped**

**Exit:** AC-5 — release-risk reproduces historical episodes with agreed recall/lead time.

---

## Phase 7 — Backend API (public, no auth)

*Goal: serve everything the frontend needs over open REST/JSON + GeoJSON.*

- [ ] Scaffold FastAPI app + `core/` wiring + `/health`, `/health/ready` →06-T01
- [ ] Async SQLAlchemy session + read repositories + pagination →06-T02
- [ ] Endpoints (all public): reservoir catalogue/detail/status; timeseries; forecast; release-risk (current/fleet/history); accuracy/backtest; pipeline/system health →06
- [ ] GeoJSON layers: AOI, water-mask (vector-simplified, D5), catchment, reservoir markers w/ `risk_level` →06
- [ ] Admin endpoints (open in v1): Prefect pipeline trigger/monitor, reservoir/AOI management →06
- [ ] CSV/PDF export (situation report) →06
- [ ] OpenAPI 3.1 contract published for the frontend →06
- [ ] ~~`/auth/*`, RBAC, `/alerts/*`~~ **descoped**

**Exit:** AC-7 (data freshness served) + AC-9 (health/logging/backups) for the serving layer.

---

## Phase 8 — Frontend (no login, no alerts view)

*Goal: modern, responsive dashboard + real-time map.*

- [ ] Scaffold `web/` (Vite+TS, Tailwind + shadcn/ui, Recharts, Vitest/Playwright/MSW) →07-T01
- [ ] App shell + routing + AsyncBoundary (loading/empty/error/**stale**) primitives →07-T03
- [ ] Typed API client (Axios + Zod) + TanStack Query + MSW fixtures →07-T04
- [ ] Leaflet map: risk-coloured markers + AOI / water-extent / catchment overlays →07-T05
- [ ] Overview + reservoir detail (KPI cards, trend chart cur/last/normal) →07
- [ ] Forecast page (1–14 day band + FRL line + baseline) + release-risk outlook panel →07
- [ ] Accuracy page (estimate-vs-truth, residuals, **labelled "historical backtest"**) →07
- [ ] Admin/health page (pipeline runs, reservoir/AOI management) →07
- [ ] Data-freshness/staleness indicators (14-day default, D8) →07
- [ ] Lock 4-tier colour-blind-safe risk palette (icon + label) →07 (D11)
- [ ] ~~Login / role routing / alerts inbox~~ **descoped**

**Exit:** AC-6 — dashboard renders map, risk indicators, KPIs, forecast/accuracy charts.

---

## Phase 9 — Hardening & automation

*Goal: the lights-out, observable, reproducible system.*

- [ ] Full automated RS→DE→ML→serve chain on schedule (Prefect) →01/04 (AC-1)
- [ ] Backtest gate + data-validation gate enforced in CI →01 (AC-12)
- [ ] Structured logging, health endpoints, run history surfaced →01 (AC-9)
- [ ] Automated DB backups + recovery objectives →01 (NFR-REL-4)
- [ ] Graceful degradation: serve forecast-based risk + staleness flag when imagery is stale →01 (NFR-REL-6)
- [ ] `docs/` runbook + clean-checkout reproducibility check →01 (AC-8)

**Exit:** all in-scope acceptance criteria closed (AC-1…AC-8, AC-10, AC-12; AC-6/7/9 as scoped; AC-5 primary).

---

## Descoped vs the plans (for later reconciliation)

The domain plans (`01`–`07`) and `requirements.md` still describe **auth/RBAC** and the **alert/notification system**. These are intentionally cut for v1. If desired, reconcile those docs (Non-Goals, AC-9/AC-11, §5.5/§5.6/§5.7, the Alert/User entities) to match this scope — or leave them as documented v2 candidates.
