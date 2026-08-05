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

- [x] Scaffold monorepo + `uv` workspace; `core/`, `db/`, `pipelines/`, `orchestration/`, `api/`, `web/`, `infra/`, `tests/` →01-T01
- [x] `.gitattributes` LF enforcement + `Taskfile.yml` (Windows host, run inside containers) →01
- [x] Shared multi-stage `uv` Python base image (`infra/docker/python.Dockerfile`) →01-T05
- [x] `docker-compose` (base/dev/prod): `postgres`+PostGIS, `mlflow`, `prefect-server`, `prefect-worker`, `api`, `web`, `pipeline-worker`, `proxy` (Caddy) →01-T10 (AC-8)
- [x] `.env.example` + file-mounted secrets convention; `geeservice.json` git-ignored, wired as `GEE_SA_KEY_FILE` →01
- [x] `DataAccessBackend` ABC + `GEEBackend` + `FixtureBackend` (the swappable GEE seam) →01-T12
- [x] `core/` SQLAlchemy 2.x models + Pydantic v2 schemas mirroring the frozen contract →02-T01
- [x] Alembic baseline migration (applies + round-trips on PostGIS; `alembic check` clean) →02
- [x] Contract tests: `Observation`/`ABT`/`ForecastForcing` schema matches `contract_version` (7 tests) →01/02
- [x] CI skeleton: ruff + mypy + lockfile check + pytest + `alembic upgrade/check` on ephemeral PostGIS →01-T20 (AC-12 partial)

**Exit:** ✅ migrations apply + round-trip; CI gates green locally (ruff/format/mypy/pytest/lockfile); compose config valid. _Note: a local Postgres owns host 5432 — use `POSTGRES_HOST_PORT` to republish (see README)._

**Phase-0 deviations from plan (recorded):** Python pinned **3.13** (host has 3.13/3.14; mature geospatial wheels) not 3.12; `area_confidence`/`layover_shadow_fraction` use `float`/DOUBLE per the **contract** (plan 02 §5.3 said `real` — a plan bug); compose host Postgres port parameterised via `POSTGRES_HOST_PORT`.

---

## Phase 1 — DB schema (no auth/alert tables)

*Goal: the canonical physical schema everything writes/reads.*

- [x] `reservoir` (AOI + catchment geom SRID 4326, FRL, capacity, `release_thresholds` jsonb, rule-curve proxy, `orbit_relative`/`pass_direction`) →02-T02
- [x] `reservoir_capacity_history` (sedimentation / time-varying capacity) →02
- [x] `observation` (contract §1, incl. `extraction_method='stub'` support) →02-T03
- [x] `ground_truth` (bulletin columns, `row_quality`) →02
- [x] `ground_truth_match` (AC-2 evidence) →02-T04
- [x] `rating_curve` (blended; observed/extrapolated ranges; `dem_epoch_waterline_m`) →02-T04
- [x] `catchment_forcing` **+ `evaporation` column (contract v3)** →02 / contract bump
- [x] `forecast_forcing` (horizon-keyed, contract §3) →02
- [x] `analytical_base_table` + `abt_current` view (contract §2, versioned snapshot) →02-T05 (AC-10)
- [x] `model_version`, `prediction`, `release_risk` (append-only, trigger-enforced) →02
- [x] `pipeline_run` (observability/idempotency) →02
- [x] ~~`app_user`/`role`/`user_role`~~ **descoped (no auth)**
- [x] ~~`alert`~~ **descoped (no alert system)**

**Action:** ✅ bumped `docs/contracts/observation-and-abt.md` to `contract_version: 3` (added `evaporation`), changelog updated, `CONTRACT_VERSION` in lockstep, parity test green.

**Exit:** ✅ all 13 tables migrated (0002), `alembic check` clean, downgrade→upgrade round-trips; integration tests pass (SRID 4326, idempotent upsert, append-only trigger, one-active-curve partial-unique, CHECK constraints); ruff/format/mypy/pytest(20) green.

---

## Phase 2 — Data Engineering: bulletins → ABT (stub Observations)

*Goal: a populated, leakage-free ABT so ML + serving can start before real SAR.*

- [x] Promote `pipelines/build_unified_dataset.py` cleaning/dedup/quarantine to `de/cleaning.py` →04-T02
- [x] Bulletin bronze→silver ingest (`data/historical/reservoir_timeseries.csv`) →04-T02
- [x] Generate **stub `Observation`** rows (invert rough bulletin curve) →04 / contract stub rule
- [x] Fuse Observations ↔ ground-truth → `ground_truth_match` (nearest ±N, default ±5d) →04-T04
- [~] Catchment delineation — **placeholder** geometry seeded; real MERIT `upa`/`pyflwdir`/HydroBASINS trace deferred to Phase 3 (needs GEE) →04-T06
- [~] Hydromet ingest + catchment aggregation — **wired behind `DataAccessBackend`** (real §6.6 asset IDs, real antecedent-index/degree-day-melt logic) incl. `evaporation`; values are fixture-stubbed until GEE auth executes →04-T07
- [~] `ForecastForcing` ingest — structure + point-in-time GFS run-selection logic built; values fixture-stubbed (real `NOAA/GFS0P25` pull behind backend) →04
- [x] `build_abt` — point-in-time builder (IST spine, backward `merge_asof`, versioned, quality/freshness flags); **leakage probe = 0** →04-T10 (AC-10)
- [x] Data-validation suite (**pandera** schemas: bulletins + ABT); GE checkpoint + CI wiring deferred →04 (AC-12)
- [ ] Prefect flows + RS→DE→ML trigger chain — **deferred to Phase 9** (orchestration; logic lives in `de/pipeline.py:run_de_pipeline`) →04

**Exit:** ✅ ABT v1 populated (~11.9k rows, 3 reservoirs × daily IST) & **leakage-tested** (AC-10 probe + recency ≥ 0); pandera validation green; pipeline idempotent. _GEE-dependent forcing values + Prefect orchestration wired but executed against the fixture backend / deferred — see [~] items._

---

## Phase 3 — Remote Sensing: real water extraction

*Goal: real `Observation` rows replace stubs.*

- [x] GEE client wrapper over `DataAccessBackend` (no raw `ee.Initialize`) — `gee_client.py` →03-T01
- [~] AOI bootstrap from JRC GSW — derivation **logic** built (`aoi.py`: occurrence→bbox→buffer→WKT); real GSW pull + per-AOI eyeball deferred (needs GEE) →03-T02
- [~] Reservoir orbit/AOI config — orbit/pass stored on `reservoir` (placeholder values); **freezing real orbit numbers (D1)** needs GEE coverage analysis, deferred →03-T03
- [~] SAR preprocessing — `calibrate.py` (dB↔linear round-trip, border-noise mask); **terrain flattening (γ⁰) + speckle** are EE-server-side, deferred →03-T06
- [ ] **DEM-based layover/shadow masking** — deferred (needs DEM + EE viewing geometry) →03-T07
- [x] `WaterExtractor` plugin ABC + registry; cold-start extractors (`otsu_vh`, `kmeans`, `gmm`) — real array algorithms, tested →03 / ADR-0007
- [x] True-area (pixel-count × true pixel area, never lat/long counts); per-area confidence (separability, compactness, layover) — `area.py`, monotonicity tested →03
- [ ] DEM hypsometric-shape handoff — deferred to Phase 4 ground-truthing (needs DEM) →03 / ADR-0004
- [~] Extraction harness — per-regime **robust selection** built + tested (`harness.py`); MLflow registration deferred →03-T16 (AC-2 input)
- [x] Emit real `Observation` rows replacing stubs (`run_rs_pipeline`); area↔fill correlation > 0.9 →03

**Exit:** ✅ real (non-stub) Observations in DB via the extractor framework; `otsu`/`kmeans`/`gmm` recover ~correct water fraction with high separability; robust harness selection + AOI/area/confidence/calibration logic all tested. _GEE-execution-dependent steps (S1 retrieval, γ⁰, layover, DEM hypsometry, frozen orbits, MLflow) wired/deferred — see [~]/[ ] items._

---

## Phase 4 — Ground-truthing & blended rating curve ⛔ (AC-2 gate)

*Goal: prove SAR-derived storage reproduces known history within tolerance.*

- [x] Matched-pairs reader (contract-bound: `ground_truth_match` ⋈ `ground_truth`) →05-T01
- [x] Nearest-match `GroundTruthMatch` build (reused from DE fusion, ±5d) →05-T02
- [x] Empirical area↔storage↔level fit (`ml/curve.py`, FRL/capacity anchor, observed-range flag) →05-T04
- [~] DEM-blended curve — `fit_type='empirical'` persisted with observed-range + `is_extrapolated`; DEM half (above-max → FRL) deferred until DEM available (ADR-0004) →05-T05
- [~] Extraction-method validation — robust harness selection built (Phase 3); per-method co-fit + MLflow registration loop deferred →05-T06
- [x] ⛔ **AC-2 acceptance gate**: held-out fill-% MAE **≤10%**, versioned `RatingCurve` (one active/reservoir), Pass-2 `derived_*`/residual backfill →05-T07 (AC-2)

**Exit:** ✅ AC-2 gate **passes** on real (non-stub `otsu_vh`) Observations; 3 versioned active curves; derived storage/level + residuals backfilled. _⚠️ MAE is artificially low because SAR areas are synthetic — this validates the gate machinery + curve fit, not real extraction accuracy (needs live GEE). The DEM blend is deferred._

---

## Phase 5 — Estimation & Forecasting

*Goal: the validated predictive engine.*

- [x] Estimation bridge (latest area → storage/level/fill via active rating curve) wired into inference — `ml/estimation.py` →05
- [x] Pooled Δ-fill forecaster (1–14 day, direct multi-horizon) with **conformal intervals** — `ml/forecaster.py` →05 / ADR-0006
- [x] Persistence + Normal-Storage climatology baselines — `ml/baselines.py` →05
- [x] Walk-forward holdout CV; **skill-vs-baseline computed/recorded** →05 (AC-4)
- [x] Persist `Prediction` rows (1–14 day, conformal intervals, `model_version` + `abt_version` provenance) →05 (AC-3)

**Exit:** ✅ machinery validated — model trains pooled, conformal intervals bracket predictions, baselines computed, 42 `Prediction` rows persisted with provenance, estimation bridge maps area→storage. _⚠️ **AC-4 not met on synthetic forcing**: with zero GEE forcing there is no inflow signal, so persistence (MAE ~2.5%) beats the model (~5%) at short horizons — the expected, honest result. Real GFS precip/snowmelt forcing is required for the forecaster to earn its skill (ADR-0006's whole premise). AC-3/AC-4 numbers are machinery checks pending live GEE._

---

## Phase 6 — Release-risk layer (compute + persist, no alerting)

*Goal: the user-facing risk indicator — transparent, not a classifier.*

- [x] Release-risk layer: forecast trajectory vs FRL/threshold bands **net of the Normal-Storage rule curve** — `ml/release_risk.py` (transparent function, ADR-0001) →05
- [x] Risk levels (Low/Watch/Warning/Imminent), lead time, contributing factors (explainable) →05
- [x] Per-reservoir release-threshold bands frozen in reservoir config (watch 90 / warning 95 / imminent 98, D7; seeded Phase 2) →02/05
- [x] Persist `ReleaseRisk` rows (append-only audit, conformal-interval-aware probability) →05
- [x] Episode backtest — detect near-FRL monsoon-peak episodes across 11 years; risk logic fires Watch+ with mean lead ≥ 3 days →05 (AC-5)
- [x] ~~Alert generation / acknowledgement / audit~~ **descoped**

**Exit:** ✅ release-risk computed + persisted per reservoir (transparent, not a classifier, ADR-0001); AC-5 backtest detects historical near-FRL episodes and the risk logic reaches Watch+ with usable lead. _Per ADR-0001/0005 the recall/precision statistic is not a v1 gate (no live ground truth); demonstrated as backtested case studies on the actual approaches._

---

## Phase 7 — Backend API (public, no auth)

*Goal: serve everything the frontend needs over open REST/JSON + GeoJSON.*

- [x] FastAPI app + `core/` wiring + `/health`, `/health/ready` (Phase 0) →06-T01
- [x] Read repositories + `get_db` dependency (override-able for tests) + pagination (timeseries `limit`) →06-T02
- [x] Endpoints (all public): reservoir catalogue/detail/status; timeseries; forecast; fleet release-risk; accuracy →06
- [x] GeoJSON: reservoir markers w/ `risk_level` (`ST_AsGeoJSON` FeatureCollection) — AOI/water-mask/catchment layers deferred →06
- [~] Admin endpoints — deferred to Phase 9 (Prefect trigger/monitor needs the running worker) →06
- [ ] CSV/PDF export — deferred (situation report) →06
- [x] OpenAPI (FastAPI auto `/openapi.json`) published for the frontend →06
- [x] ~~`/auth/*`, RBAC, `/alerts/*`~~ **descoped**

**Exit:** ✅ the whole platform is queryable over HTTP — catalogue/detail/status, time series, 1–14 day forecast w/ conformal intervals, fleet release-risk, accuracy, GeoJSON markers, OpenAPI; freshness served via `last_acquisition_date` (AC-7). Tested via TestClient with a `get_db` override (no commits). _Admin/Prefect endpoints + CSV/PDF export deferred to Phase 9._

---

## Phase 8 — Frontend (no login, no alerts view)

*Goal: modern, responsive dashboard + real-time map.*

- [x] Scaffold `web/` (Vite + React + TS, **Recharts**, Leaflet) — lean stack (Tailwind/shadcn/Vitest/MSW deferred) →07-T01
- [x] App shell + loading/empty/error + freshness states (typed components) →07-T03
- [x] Typed API client (`fetch`) over the FR-API endpoints (Axios/Zod/TanStack deferred) →07-T04
- [x] Leaflet map: **risk-coloured CircleMarkers** from `/geojson/reservoirs`; AOI/water-extent/catchment overlays deferred (need real geometry) →07-T05
- [x] Reservoir detail: KPI cards (fill, level vs FRL, storage, release prob · lead) + **trend chart (fill vs seasonal normal)** →07
- [x] Forecast panel (1–14 day predicted line + **conformal interval band**) + release-risk badge →07
- [~] Accuracy page — `/accuracy` endpoint serves it (labelled "historical backtest"); dedicated page deferred →07
- [ ] Admin/health page — deferred to Phase 9 →07
- [x] Data-freshness indicator (`last_acquisition_date` in header; 14-day threshold, D8) →07
- [x] 4-tier colour-blind-safe risk palette + label (`RISK_COLOR`, D11) →07
- [x] ~~Login / role routing / alerts inbox~~ **descoped**

**Exit:** ✅ **Map-centric GIS console** (React + Leaflet + Recharts) builds clean — **satellite basemap** (Esri) + Street, a **layer control** with real overlays (reservoir AOI from JRC GSW, catchment from HydroBASINS, **Sentinel-1 water extent**), risk-coloured dam markers, a risk legend, fleet risk chips, and a side panel (KPIs, fill-vs-normal trend, 1–14 day forecast with conformal band, SAR water-extent line, staleness banner). Numeric fields coerced defensively. _Verified to build with Node 24; not browser-rendered here._

**Real GEE now wired (was deferred):** `remote_sensing/gee_real.py` + `scripts/populate_geometry.py` derive real AOI (JRC GSW), catchment (HydroBASINS) and Sentinel-1 water masks live from Earth Engine (service-account `geeservice.json`, project verified working) and persist them to PostGIS (`reservoir.aoi_geom`/`catchment_geom`, `observation.water_mask_geom` via migration 0003). API serves them at `/geojson/{aoi,catchment,water-extent}`. `start.bat` runs the populate step (non-fatal). _The historical accuracy figures remain synthetic-machinery until full historical SAR extraction runs; the map geometry is real._

**Exit:** AC-6 — dashboard renders map, risk indicators, KPIs, forecast/accuracy charts.

---

## Phase 8A — Expert Hydrologic Map Foundations

*Goal: create a HydroSHEDS-style hydrologic map for each dam/reservoir that is scientifically defensible, visually legible, and ready to support downstream flow animation and forecast explanation.*

### 8A.1 GIS/Hydrology Design Decisions

- [x] Define the map products: fleet overview, selected-reservoir catchment view, printable/exportable static hydrologic map, and interactive analysis map — ADR-0008 + `hydrologicMapPolicy.ts`
- [x] Select authoritative source hierarchy: MERIT Hydro for dam-specific contributing area and routing where available; HydroBASINS/HydroSHEDS for basin display units; HydroRIVERS/MERIT lines for drainage visualization — ADR-0008 + `HYDROLOGIC_SOURCE_HIERARCHY`
- [x] Choose HydroBASINS levels per use case: level 5-6 for national/regional context, level 7 for reservoir catchment overview, level 8-9 only for zoomed analysis if performance permits — `HYDROBASINS_LEVEL_POLICY`
- [x] Record that HydroBASINS polygons are cartographic/aggregation units; true contributing area should be validated against MERIT Hydro flow direction/accumulation and published basin areas — ADR-0008 + `HYDROBASINS_CARTOGRAPHIC_WARNING`
- [x] Define hydrologic styling rules before implementation: upstream catchment boundary, sub-basin hierarchy, main stem, tributaries, reservoir waterbody, dam point, and transboundary/context boundaries — `HYDROLOGIC_LAYER_STYLES`
- [x] Define acceptable simplification tolerances by zoom/export scale so drainage structure remains legible without distorting catchment topology — `HYDROLOGIC_SIMPLIFICATION_POLICY`

### 8A.2 Required Datasets

- [x] DEM/elevation: use MERIT DEM or SRTM/Copernicus DEM for terrain, hillshade, slope, aspect, and elevation tint — `hydrologic-map-datasets.md` + `hydrologicDatasets.ts`
- [x] Basin polygons: HydroBASINS `HYBAS_ID`, `NEXT_DOWN`, `MAIN_BAS`, area, and Pfafstetter/topology attributes where available — dataset catalog requires topology fields
- [x] Flow network: HydroRIVERS or MERIT Hydro-derived stream vectors with upstream area, stream order, and main-stem/tributary classification — dataset catalog requires stream order/upstream area/downstream id
- [x] Reservoir geometry: JRC Global Surface Water max extent, existing AOI polygons, latest Sentinel-1 water extent, and dam/reservoir points — dataset catalog separates max extent from current SAR extent
- [x] Hydromet context for dynamic maps: ERA5-Land precipitation/temperature/SWE, GPM IMERG cross-check precipitation, MODIS snow cover, GLDAS snow variables where useful, and NOAA GFS forecast forcing — dataset catalog records primary/cross-check roles
- [x] Political/context layers: country/state/district boundaries and major settlements only at low opacity so hydrology remains primary — dataset catalog marks context-only layers
- [x] Provenance metadata for every layer: source dataset, version/date, resolution, processing date, simplification tolerance, projection, and known limitations — `layer_provenance` contract added

### 8A.3 Data Preparation Pipeline

- [x] Build a reproducible `prepare_hydrologic_map_layers` pipeline step separate from live SAR extraction — pure vector prep spine added in `remote_sensing.hydrologic_map`; external DEM/flowline extraction remains a data-source task
- [x] Reproject and validate all source geometries to WGS84 for web serving; use equal-area projection for area/length calculations before returning to WGS84
- [~] Derive DEM hillshade, slope, and elevation color raster tiles for the pilot region — interactive v1 uses Topo basemap terrain context; local DEM tile derivation deferred until DEM assets are added
- [~] Delineate or validate each reservoir's upstream contributing area from the dam point using MERIT Hydro flow direction/accumulation where possible — HydroBASINS catchments are wired and documented; MERIT validation remains open as an external data task
- [x] Clip HydroBASINS sub-basins to each validated reservoir catchment and retain `HYBAS_ID`/`NEXT_DOWN` topology
- [x] Clip drainage network to each reservoir catchment and classify streams by Strahler/order or upstream contributing area
- [~] Compute sub-basin summary attributes: area, mean/min/max elevation, mean slope, distance to reservoir, upstream/downstream ids, headwater flag, and downstream path length — area/distance/topology done; DEM elevation/slope still open
- [x] Compute flowline summary attributes: length, order, upstream area, main-stem flag, downstream id, and whether it intersects/terminates near the reservoir
- [x] Generate multiple geometry resolutions: raw/internal, web-simplified, and export-quality — `GEOMETRY_RESOLUTIONS` policy added
- [~] Store layer-preparation quality flags: invalid geometry repaired, clipped slivers removed, missing topology, disconnected flowline, and low-confidence catchment boundary — vector geometry + topology QA flags are attached during prep; low-confidence catchment boundary remains a future validation input

### 8A.4 Database + API Contracts

- [~] Add or extend tables for persistent hydrologic map layers: `catchment_subbasin`, `catchment_flowline`, `district_boundary`, and `hydrologic_layer_provenance` — vector/static layers are persisted; terrain tiles deferred until DEM assets are added
- [x] Keep static map attributes separate from time-varying forcing so base cartography can be cached indefinitely — hydrologic geometry/provenance tables are separate from `catchment_forcing` and forecast inputs
- [~] Add spatial indexes and reservoir-scoped indexes for all hydrologic map tables — `catchment_subbasin`, `catchment_flowline`, and `district_boundary` are indexed; terrain tile indexes deferred
- [x] Add `/geojson/hydrologic/subbasins?reservoir_id={rid}&resolution=web|export` endpoint
- [x] Add `/geojson/hydrologic/flowlines?reservoir_id={rid}&min_order={n}` endpoint
- [~] Add `/tiles/hydrologic/terrain/{z}/{x}/{y}` or equivalent static terrain tile endpoint if local terrain tiles are generated — deferred because local DEM terrain tiles are not generated; Topo basemap is used for v1 context
- [x] Add `/hydrologic/layers/provenance?reservoir_id={rid}` endpoint so users can inspect source versions and limitations
- [x] Add typed Pydantic and TypeScript contracts for all hydrologic map properties — Pydantic + TypeScript contracts cover catchments, sub-basins, flowlines, provenance, water extent, and district context; terrain tiles deferred

### 8A.5 Cartographic Rendering

- [x] Add a terrain/hillshade basemap option under the existing satellite and street layers — Topo basemap added and made the hydroshed-view default
- [x] Render catchment boundary with a strong but non-water color so it reads as a drainage divide, not a river
- [~] Render HydroBASINS sub-basins with subtle elevation/physiographic tint and hover emphasis — muted physiographic tint + hover done; DEM-derived elevation tint deferred
- [x] Render rivers with width proportional to upstream area or stream order; show only major streams at low zoom and progressively reveal tributaries at higher zoom
- [x] Render reservoir waterbody and current SAR water extent distinctly: max extent as muted outline, current extent as high-confidence water fill
- [x] Add labels/tooltips for dam point, reservoir name, basin name, main stem, and selected sub-basin statistics — selected dam/reservoir label plus catchment, sub-basin, and flowline tooltips added
- [x] Add a professional legend explaining terrain tint, stream hierarchy, catchment boundary, reservoir extent, and data source/date — hydrologic legend includes layer symbology and provenance source/version/date rows
- [x] Add print/export-friendly styling for static PNG/PDF map exports later, but keep v1 focused on interactive Leaflet rendering — print CSS hides controls/docks and preserves map/legend for browser PNG/PDF export

### 8A.6 Hydrologic QA + Validation

- [~] Compare computed catchment area for Gobind Sagar, Pong, and Thein against published basin/catchment area references — QA script compares Gobind Sagar against BBMB reference; Pong/Thein references still need sourcing
- [~] Verify dam point placement relative to flow accumulation and reservoir outlet; correct with manual snap/override if the point falls off-network — documented as a manual/MERIT QA limitation in `docs/runbooks/hydrologic-map-qa.md`
- [~] Check that upstream traversal includes known transboundary headwaters where hydrologically correct — documented as manual visual/domain QA in `docs/runbooks/hydrologic-map-qa.md`
- [~] Check that flowlines terminate consistently at or upstream of each reservoir, not downstream of the dam — sub-basin topology classifies the single external outlet separately; persisted HydroRIVERS flowlines are present and valid, outlet snapping/manual dam-network QA remains open
- [~] Check for disconnected tributaries, reversed lines, duplicate flowlines, basin slivers, and invalid polygons — `scripts/qa_hydrologic_layers.py` checks persisted sub-basin geometry/topology plus HydroRIVERS flowline presence/validity; reversed/disconnected visual QA remains open
- [~] Visually QA each reservoir map at overview, catchment, and tributary zoom levels — visual QA checklist documented; final sign-off remains manual
- [x] Document limitations: HydroBASINS resolution, dam-not-at-outlet issue, DEM voids/errors, glacier/snow uncertainty, and rainfall/snow product limitations in high mountains — see `docs/runbooks/hydrologic-map-qa.md`

### 8A.7 Implementation Order

- [x] Milestone 1: static selected-reservoir map with terrain, catchment boundary, dam point, reservoir extent, and major rivers
- [x] Milestone 2: HydroBASINS sub-basin hierarchy with topology-aware hover and legend
- [x] Milestone 3: flowline hierarchy with stream-order/upstream-area styling and zoom-dependent detail
- [x] Milestone 4: provenance panel and QA flags surfaced in the UI — legend surfaces layer provenance; QA limitations are documented in the runbook
- [x] Milestone 5: export-quality map snapshot path for reports/situation briefings — browser print/PDF export styling added for v1
- [x] Milestone 6: handoff to Phase 8B animated flow visualization using the validated topology and flowline layers — validated HydroBASINS topology and HydroRIVERS flowlines are persisted and served

**Exit:** each pilot reservoir has a defensible HydroSHEDS-style hydrologic map: shaded terrain, validated upstream catchment, HydroBASINS sub-basins, hierarchical drainage network, reservoir extent, dam point, legend, provenance, and QA notes.

---

## Phase 8B — Hydrological Flow Visualization

*Goal: turn HydroBASINS/HydroSHEDS catchments from static boundaries into an explainable upstream-to-reservoir flow view showing how rainfall and snowmelt contribute to reservoir rise and release-risk.*

### 8B.1 Data Model + Contracts

- [ ] Add hydrology attribution contract for sub-basins: `area_km2`, `upstream_area_km2`, `stream_order`, `distance_to_reservoir_km`, `routing_lag_days`, `precip_24h_mm`, `precip_7d_mm`, `snow_cover_pct`, `degree_day_melt_mm_day`, `contribution_score`
- [x] Add flowline contract for river/drainage network features clipped to each reservoir catchment
- [x] Decide v1 routing model: simple topology/routing-lag visualization first, no calibrated distributed hydrological model
- [x] Keep terminology aligned: rainfall/snowmelt are catchment-forcing features; they explain forecast/release-risk, not directly observed release events

### 8B.2 Backend Persistence

- [x] Add `catchment_flowline` table keyed by `(reservoir_id, flowline_id)` with geometry, upstream area, stream order, downstream id, and provenance
- [ ] Add optional hydrology columns or companion table for per-sub-basin time-varying forcing summaries
- [x] Add migration with PostGIS indexes for sub-basin and flowline geometries
- [x] Add repository queries for selected-reservoir hydrology GeoJSON — first slice: topology-derived `/geojson/flow-edges`

### 8B.3 Data Extraction Pipeline

- [x] Clip HydroRIVERS/MERIT Hydro flowlines to each reservoir catchment
- [x] Derive sub-basin centroids and `NEXT_DOWN` topology edges from `catchment_subbasin`
- [x] Compute approximate downstream distance from each sub-basin to reservoir
- [x] Compute first-pass routing lag from distance/slope/stream order or configurable velocity assumptions — first slice uses distance / 75 km/day, clamped 0.25-7 days
- [ ] Aggregate catchment forcing per sub-basin where source resolution supports it
- [ ] Fall back honestly to catchment-level forcing when per-sub-basin forcing is unavailable

### 8B.4 API

- [ ] Add `/geojson/subbasins/hydrology?reservoir_id={rid}&date={date}` endpoint
- [x] Add `/geojson/flowlines?reservoir_id={rid}` endpoint — implemented as `/geojson/hydrologic/flowlines?reservoir_id={rid}&min_order={n}`
- [x] Add `/geojson/flow-edges?reservoir_id={rid}&date={date}` endpoint for topology-derived animation paths — implemented as `/geojson/flow-edges` fleet collection, frontend filters by selected reservoir
- [x] Add Pydantic GeoJSON property schemas for hydrology sub-basins, flowlines, and flow edges
- [~] Add API tests for empty-data degradation, selected-reservoir filtering, and stable GeoJSON shape — flow-edge contract test added; local run skipped without DB fixture

### 8B.5 Frontend Map Layers

- [ ] Add `HydrologySubBasinLayer` choropleth for rainfall, snowmelt, antecedent precipitation index, and contribution score
- [x] Add `FlowLineLayer` with river width proportional to upstream area / stream order
- [x] Add `FlowTransportLayer` for animated downstream movement from headwaters toward the selected reservoir — implemented as `FlowEdgeLayer` on topology-derived paths
- [~] Add layer chips: `Rainfall`, `Snowmelt`, `Flow`, `Forecast impact` — first slice adds `Flow paths`
- [ ] Add legend for hydrology modes with units and data freshness
- [~] Add hover tooltips for sub-basins: basin id, 7d rainfall, snow cover, melt potential, lag, contribution score — first slice adds flow-path tooltips with basin id, distance, and lag proxy
- [x] Preserve existing catchment, sub-basin, water extent, and SAR tile layers

### 8B.6 Animated Downstream Transport Plan

- [x] Build topology edges from each sub-basin centroid to its `next_down` sub-basin centroid; terminate at the reservoir marker when `next_down = 0` or exits the selected catchment
- [x] Start with centroid-to-centroid SVG polylines for the first implementation; later snap paths to HydroRIVERS/MERIT flowlines for more realistic river-following movement
- [x] Render static faint flow edges under animated pulses so direction remains visible when animation is paused or disabled
- [x] Render animated pulses moving downstream using SVG/CSS stroke animation or deterministic `requestAnimationFrame` interpolation along path length
- [ ] Encode pulse width/opacity by `contribution_score`, with mode colors: rainfall blue, snowmelt cyan/white, forecast impact amber/purple
- [x] Offset pulse start time by `routing_lag_days` so distant headwater contribution visibly arrives later than near-reservoir contribution
- [x] Derive first-pass `routing_lag_days = distance_to_reservoir_km / assumed_flow_velocity_km_per_day`, clamped to a useful display range such as 0.25-7 days
- [x] Mark routing lag as a visualization/inflow proxy, not a calibrated hydrological process model
- [x] Respect `prefers-reduced-motion`: disable pulses and show static arrows/flow intensity instead
- [x] Keep the animation selected-reservoir scoped and mobile-safe; avoid rendering fleet-wide flow animations at once

### 8B.7 Forecast/Release-Risk Integration

- [ ] Add reservoir-side explanation panel: recent rainfall, snowmelt, lagged inflow proxy, and forecast fill response
- [ ] Link highlighted contributing basins to release-risk contributing factors
- [ ] Show expected arrival window for active upstream forcing
- [ ] Avoid implying direct release-event observation; frame the layer as upstream forcing influencing the forecast trajectory and inherited release-risk

### 8B.8 Verification

- [~] Unit-test topology edge derivation, headwater ordering, and routing-lag calculation — API integration coverage added; pure unit extraction still open
- [x] API contract tests for hydrology GeoJSON schemas
- [~] Frontend tests for layer toggles and reduced-motion fallback — layer toggle covered; reduced-motion remains CSS/manual QA
- [ ] Manual QA: Gobind Sagar, Pong, Thein render without blocking existing map layers
- [ ] Performance check: selected reservoir map remains responsive with all hydrology layers enabled

**Exit:** selected reservoir map can explain upstream rainfall/snowmelt transport using HydroBASINS/HydroSHEDS-derived topology, flowlines, animated downstream movement, and forecast-impact context without pretending to run a full physical hydrological model.

---

## Phase 8C — PMD Weather & Forecast Layers

*Goal: integrate PMD/FFD weather observations, warning polygons, and precipitation/temperature forecast layers as secure, cache-efficient, provenance-labelled map overlays and optional catchment forcing inputs. Weather layers explain upstream forcing and forecast context; they do **not** directly observe release events.*

### 8C.0 Security + Source Governance

- [x] Treat the `imtiaz/` PMD documents as local research material only; do not commit plaintext credentials, bearer tokens, cookies, or internal PMD URLs that are not already approved for tracked docs — `imtiaz/` ignored
- [x] Add `PMD_MONITOR_URL`, `PMD_MONITOR_USER`, `PMD_MONITOR_PASS`, and optional `PMD_PUBLIC_FORECAST_API_KEY` to `.env.example` with empty placeholder values only
- [x] Store live credentials only in `.env` or deployment secrets; never pass PMD Monitor credentials to the browser — backend `Settings` fields added; no frontend exposure
- [x] Define a backend source registry for PMD/FFD endpoints with `source_name`, upstream path, cache TTL, expected geometry type, freshness policy, and operational limitations — `PMD_SOURCES`
- [x] Mark debug/probe endpoints (`/api/pmd/monitor/debug/`, NWFC debug station, raw arbitrary upstream paths) as excluded from our public API and frontend — `EXCLUDED_PMD_ENDPOINTS`
- [x] Add source attribution strings for PMD Monitor, PMD NWFC, and FFD so legends/tooltips always label weather data provenance — source registry includes attribution names

### 8C.1 Backend PMD Client Foundation

- [x] Add a dedicated backend PMD client module, separate from reservoir repositories and model code, responsible for all upstream HTTP/auth/caching behavior — `api.pmd_client`
- [x] Implement PMD Monitor login via `POST /user/login`, extracting bearer JWT from the JSON response and retaining the `ews_jwt` cookie server-side
- [x] Implement a process-local authenticated session cache protected by a lock, with proactive TTL refresh and retry-once re-login on 401/403
- [x] Handle PMD Monitor self-signed/legacy TLS using a narrowly scoped custom HTTP adapter; keep normal TLS behavior for all other external sources
- [x] Implement `_pmd_get_json`, `_pmd_post_json`, and `_pmd_get_bytes` as separate code paths so binary GeoTIFF responses are never JSON/text parsed
- [x] Implement cache-with-stale-fallback per endpoint: return fresh cache on hit, fetch on miss, serve stale-but-labelled fallback on transient upstream failure
- [ ] Normalize upstream timestamps to explicit PKT/UTC+5 metadata, preserving original source timestamp fields for auditability
- [x] Add robust data cleaning for PMD sentinel/fault values (`9999`, `999`, `-9999`, `-999`, `2147483.xxx`) before values reach frontend or forcing aggregation

### 8C.2 PMD GeoJSON Observation + Warning Contracts

- [~] Define typed Pydantic schemas and TypeScript contracts for PMD station observations, NWFC observations, warning polygons, monsoon warnings, lightning strikes, GLOF observations, city forecasts, and FFD water levels — backend Pydantic station observation contract added; TypeScript and remaining datasets still open
- [ ] Represent nested JSON-string upstream fields (`fc`, `elements`, `gauges`, selected warning geometry fields) as parsed native JSON in our API responses where safe and stable
- [~] Preserve raw upstream IDs/codes (`station_id`, `code`, `data_type`, `model`, `forecast_time`) so map features can be joined, inspected, and refreshed deterministically — station `station_id`/`code` preserved
- [~] Add freshness fields to every PMD response: `source`, `source_timestamp`, `fetched_at`, `cache_status`, `stale`, and `ttl_seconds` — station endpoint includes these fields where upstream provides timestamps
- [x] Return empty valid FeatureCollections for normal no-data conditions; reserve non-2xx responses for auth/config/server failures — covered for PMD station endpoint
- [~] Add fixture responses for representative non-empty, empty, stale-cache, sentinel-value, and malformed-nested-JSON cases — no-network station tests cover non-empty, empty, stale, and sentinel cleaning

### 8C.3 Backend PMD GeoJSON API

- [x] Add `/weather/pmd/monitor/stations` for live SYNOP/METAR/AWS station observations with temperature, rainfall, wind, humidity, pressure, visibility, and warning color fields
- [ ] Add `/weather/pmd/nwfc/observations` for NWFC station observations and weather-text/icon classification inputs
- [ ] Add `/weather/pmd/monitor/warnings` for active warning polygons with severity, hazard element, model, forecast time, data time, message, and area
- [ ] Add `/weather/pmd/monitor/monsoon` for monsoon-specific warnings and rainfall forecast text
- [ ] Add `/weather/pmd/monitor/glof-observations` for GLOF station readings, connectivity, alert level, rainfall, flow, water level, and temperature
- [ ] Add `/weather/pmd/monitor/lightning?hours=1..48` for recent lightning strike points
- [ ] Add `/weather/ffd/waterlevels` for FFD river gauge discharge/status points and parsed gauge arrays
- [ ] Add `/weather/pmd/monitor/city-forecast` for city current conditions plus parsed 12-step forecast arrays
- [ ] Add endpoint-level timeout handling so one slow upstream source cannot block unrelated reservoir/hydrologic map endpoints
- [~] Add repository-free API tests using mocked PMD client responses; avoid network calls in tests — station endpoint covered with dependency override fake client

### 8C.4 PMD Forecast Raster Discovery

- [ ] Confirm which PMD Monitor prediction element codes are live and stable before implementing each raster layer; do not infer codes from display labels alone
- [ ] Confirm the four WRFPRS precipitation accumulation elements: `HOURTPE`, `SIXTPE`, `TWELVETPE`, `DAYTPE`
- [ ] Discover and verify codes for 7d precipitation, cumulative precipitation, 6h/12h/24h rainfall-and-snow, and temperature/precipitation anomaly layers before adding them to the product UI
- [ ] Download one real GeoTIFF per confirmed element and inspect band count, CRS, nodata value, pixel value range, extent, and unit using GDAL
- [ ] Extract official PMD color ramps from the source portal JavaScript where available; clearly label any fallback color ramp as our own choice, not PMD-official
- [ ] Record confirmed elements, units, accumulation windows, color stops, source run cadence, and known caveats in a tracked contract document

### 8C.5 Forecast Raster Processing + Tile/Image Serving

- [ ] Add a forecast-raster element registry keyed by stable frontend IDs (`pmd_pred_hourtpe`, etc.) with upstream `data_type`, `element`, label, unit, accumulation window, color ramp, and max frame policy
- [ ] Add backend endpoint `/weather/pmd/predictions/{element_key}` returning `{element, label, unit, run, steps}` where each step has `date`, `bounds`, `coordinates`, `url`, and `cache_status`
- [ ] Fetch latest model runs using `/api/modelTimeList?data_type=<data_type>&element=<element>` with 30-minute metadata TTL
- [ ] Fetch per-run frame lists using `/api/model?data_type=<data_type>&element=<element>&date_time=<run>` with 3-hour metadata TTL
- [ ] Thin forecast frames for browser performance: dense early window, sparse later window, with element-specific caps to avoid hundreds of simultaneous image overlays
- [ ] Convert raw GeoTIFF frames server-side with GDAL: download bytes, write temp GeoTIFF, warp to EPSG:3857, colorize with fixed ramp, add alpha, persist PNG + JSON sidecar
- [ ] Compute image bounds from all four warped raster corners; do not use a two-corner shortcut
- [ ] Use deterministic on-disk cache keys per `(element, run, forecast_time)` so repeated requests avoid network/GDAL work
- [ ] Delete intermediate GeoTIFF files after conversion; retain only PNG, metadata sidecar, and optional ramp files
- [ ] Add disk-cache cleanup policy or operator command for old PMD prediction PNG/JSON files
- [ ] Add optional `?diag=1` or admin-only cache bypass for operational debugging without exposing raw upstream probes publicly

### 8C.6 Weather Layer Persistence + Catchment Aggregation

- [ ] Decide which PMD datasets remain cache-only display layers and which are persisted for modelling; avoid persisting noisy point observations unless they feed a defined product
- [ ] Add optional `weather_layer_provenance` or reuse `hydrologic_layer_provenance` only if semantics remain clear; do not conflate static hydrologic provenance with dynamic weather freshness
- [ ] Add catchment aggregation job for PMD forecast rasters: clip/average/sum precipitation over `reservoir.catchment_geom` and optionally sub-basins where resolution supports it
- [ ] Write PMD-derived catchment precipitation forecasts to `forecast_forcing` only after unit/time-window alignment is explicit and tested
- [ ] Write observed/reanalysis-like PMD rainfall summaries to `catchment_forcing` only when source cadence and spatial representativeness are documented
- [ ] Keep PMD visual layers separate from validated forecasting inputs until walk-forward skill/backtest impact is measured
- [ ] Add source-version/freshness flags to forcing rows so downstream ML can distinguish ERA5/Open-Meteo/GFS/PMD-derived inputs

### 8C.7 Frontend Map Layer UX

- [ ] Add a `Weather` group in map controls separate from `Hydrologic layers`, with toggles for observations, warnings, lightning, GLOF, FFD gauges, and PMD prediction rasters
- [ ] Add weather layer chips that are disabled with clear copy when backend credentials/config are missing, instead of failing silently
- [ ] Render PMD station observations as clustered or density-thinned Leaflet markers at low zoom; avoid rendering hundreds of DOM markers unclustered
- [ ] Render warning/monsoon polygons with severity colors and low-opacity fill so catchment boundaries and drainage remain legible
- [ ] Render lightning as short-lived point markers with a user-selectable 1–48 hour window
- [ ] Render FFD river gauges as point markers with status color, discharge, trend, and timestamp tooltips
- [ ] Render PMD prediction PNG frames using Leaflet image overlays pinned to returned bounds/coordinates; avoid trying to render raw GeoTIFF in the browser
- [ ] Add temporal controls for PMD prediction frames that reuse the existing timeline/dock patterns without coupling to SAR acquisition dates
- [ ] Add layer legends for station weather icons, warning severity, precipitation ramps, and temperature/anomaly ramps
- [ ] Add hover/click tooltips with source timestamp, cache status, unit, and upstream source; show stale data visibly
- [ ] Keep all weather overlays selected-reservoir-aware where useful, but allow national context layers when zoomed out

### 8C.8 Weather Report / Analysis Panel

- [ ] Add a compact PMD Weather panel or tab summarizing active selected weather layers, using lazy per-section fetches and per-section loading/error states
- [ ] Group warnings by hazard type and severity, sort newest-first, and support hazard filters before enabling warning-heavy map layers
- [ ] Show selected-reservoir weather context: nearest stations, catchment 24h/7d precipitation, active warnings intersecting catchment, and forecast precipitation frames
- [ ] Add drill-down views for NWFC daily forecast, weekly outlook, rainfall reports, FFD bulletins, and station history only after the base map layers are stable
- [ ] Add HTML/CSV export later as a separate ticket; do not block map-layer integration on full report export
- [ ] Escape all third-party scraped text before rendering; React text rendering is safe by default, but any HTML injection path must be explicitly prohibited

### 8C.9 Performance + Reliability Gates

- [ ] Set frontend query stale times to match upstream TTLs; do not poll faster than source cache windows
- [ ] Abort in-flight fetches on layer toggle-off or reservoir switch to avoid stale layer flashes
- [ ] Keep PMD raster overlays memory-bounded: cap frame count, unload hidden layer groups, and avoid registering all elements at once
- [ ] Add backend metrics for upstream fetch count, cache hit/miss/stale fallback count, conversion time, generated PNG count, and endpoint latency
- [ ] Add request timeouts and circuit-breaker behavior so PMD outage does not degrade reservoir status, SAR tiles, hydrologic layers, or forecasts
- [ ] Add manual performance budget: all selected-reservoir hydrologic layers plus one PMD raster animation remains responsive on a mid-range laptop and mobile browser
- [ ] Add smoke script that checks PMD config presence, auth success, one GeoJSON endpoint, one raster metadata endpoint, and one generated PNG URL

### 8C.10 Validation + Acceptance

- [~] Unit-test sentinel-value cleaning, timestamp normalization, nested JSON parsing, element registry validation, frame thinning, and color-ramp generation — first slice covers sentinel cleaning, nested JSON parsing, source registry, auth retry, binary path, and stale cache fallback
- [ ] API-test stable response contracts for all PMD GeoJSON endpoints using fixtures, including empty/no-data and stale-cache fallback cases
- [ ] Integration-test forecast raster endpoint with a tiny fixture GeoTIFF so GDAL conversion, alpha handling, bounds, and PNG serving are deterministic in CI
- [ ] Frontend-test weather layer toggles, disabled states when PMD config is unavailable, legend rendering, stale badges, and temporal raster frame selection
- [ ] Manual QA on Gobind Sagar, Pong, and Thein: weather layers do not obscure catchment divide, drainage network, water extent, or release-risk UI
- [ ] Verify precipitation units and accumulation windows before any PMD-derived values are used in `catchment_forcing` or `forecast_forcing`
- [ ] Document operational limitations: PMD upstream availability, private/internal endpoint dependency, stale cache behavior, model-resolution limits, and non-observability of release events
- [ ] Re-run forecasting backtests before claiming PMD forecast layers improve release-risk skill

**Exit:** the app can securely display PMD/FFD live weather observations, warning polygons, and at least one optimized precipitation forecast raster layer with provenance, freshness, caching, and graceful degradation. PMD-derived data is only promoted into model forcing after explicit aggregation and validation gates pass.

---

## Phase 9 — Hardening & automation

*Goal: the lights-out, observable, reproducible system.*

- [x] Full RS→DE→ML→serve chain (`orchestration/pipeline.py:run_full_pipeline`, idempotent) — runs the whole pipeline in one pass (AC-1). _Prefect **scheduling/worker** deferred (the chain logic is ready to wrap)._ →01/04
- [x] Data-validation + backtest gates in CI — the `pytest` job is the gate (pandera DE validation, AC-10 leakage probe, AC-2 curve gate, AC-5 backtest) on ephemeral PostGIS →01 (AC-12)
- [~] Health endpoints (`/health`, `/health/ready`) + `pipeline_run` table; structured logging (`structlog`) deferred →01 (AC-9)
- [ ] Automated DB backups + RPO/RTO — deferred (ofelia/pg_dump sidecar) →01 (NFR-REL-4)
- [x] Graceful degradation: API status serves forecast-based `risk_level` + `stale`/`data_age_days` flag (14-day threshold, D8) →01 (NFR-REL-6)
- [x] Runbook (`docs/runbooks/local-bringup.md`) + **`start.bat`** one-command bring-up (verified: live API serves all endpoints) →01 (AC-8)

**Exit:** ✅ one-command live system (`start.bat`): Postgres → migrate → full pipeline → API + dashboard, browser-openable. Full chain idempotent; AC-12 gates run in CI; graceful-degradation staleness served. _Prefect scheduling, structured logging, and DB backups deferred as ops infra._

---

## Descoped vs the plans (for later reconciliation)

The domain plans (`01`–`07`) and `requirements.md` still describe **auth/RBAC** and the **alert/notification system**. These are intentionally cut for v1. If desired, reconcile those docs (Non-Goals, AC-9/AC-11, §5.5/§5.6/§5.7, the Alert/User entities) to match this scope — or leave them as documented v2 candidates.
