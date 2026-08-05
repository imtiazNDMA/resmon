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

- [~] Build a reproducible `prepare_hydrologic_map_layers` pipeline step separate from live SAR extraction — pure prep spine added in `remote_sensing.hydrologic_map`; external DEM/flowline extraction still open
- [ ] Reproject and validate all source geometries to WGS84 for web serving; use equal-area projection for area/length calculations before returning to WGS84
- [ ] Derive DEM hillshade, slope, and elevation color raster tiles for the pilot region
- [ ] Delineate or validate each reservoir's upstream contributing area from the dam point using MERIT Hydro flow direction/accumulation where possible
- [ ] Clip HydroBASINS sub-basins to each validated reservoir catchment and retain `HYBAS_ID`/`NEXT_DOWN` topology
- [ ] Clip drainage network to each reservoir catchment and classify streams by Strahler/order or upstream contributing area
- [~] Compute sub-basin summary attributes: area, mean/min/max elevation, mean slope, distance to reservoir, upstream/downstream ids, headwater flag, and downstream path length — topology-derived headwater/downstream path length implemented; DEM/elevation/area enrichment still open
- [ ] Compute flowline summary attributes: length, order, upstream area, main-stem flag, downstream id, and whether it intersects/terminates near the reservoir
- [x] Generate multiple geometry resolutions: raw/internal, web-simplified, and export-quality — `GEOMETRY_RESOLUTIONS` policy added
- [~] Store layer-preparation quality flags: invalid geometry repaired, clipped slivers removed, missing topology, disconnected flowline, and low-confidence catchment boundary — topology flags added (`duplicate_hybas_id`, `missing_downstream`, `cycle_detected`, `outlet_basin`); geometry/flowline QA still open

### 8A.4 Database + API Contracts

- [ ] Add or extend tables for persistent hydrologic map layers: `catchment_subbasin`, `catchment_flowline`, `catchment_terrain_tile`, and `hydrologic_layer_provenance`
- [ ] Keep static map attributes separate from time-varying forcing so base cartography can be cached indefinitely
- [ ] Add spatial indexes and reservoir-scoped indexes for all hydrologic map tables
- [ ] Add `/geojson/hydrologic/subbasins?reservoir_id={rid}&resolution=web|export` endpoint
- [ ] Add `/geojson/hydrologic/flowlines?reservoir_id={rid}&min_order={n}` endpoint
- [ ] Add `/tiles/hydrologic/terrain/{z}/{x}/{y}` or equivalent static terrain tile endpoint if local terrain tiles are generated
- [ ] Add `/hydrologic/layers/provenance?reservoir_id={rid}` endpoint so users can inspect source versions and limitations
- [ ] Add typed Pydantic and TypeScript contracts for all hydrologic map properties

### 8A.5 Cartographic Rendering

- [ ] Add a terrain/hillshade basemap option under the existing satellite and street layers
- [ ] Render catchment boundary with a strong but non-water color so it reads as a drainage divide, not a river
- [ ] Render HydroBASINS sub-basins with subtle elevation/physiographic tint and hover emphasis
- [ ] Render rivers with width proportional to upstream area or stream order; show only major streams at low zoom and progressively reveal tributaries at higher zoom
- [ ] Render reservoir waterbody and current SAR water extent distinctly: max extent as muted outline, current extent as high-confidence water fill
- [ ] Add labels/tooltips for dam point, reservoir name, basin name, main stem, and selected sub-basin statistics
- [ ] Add a professional legend explaining terrain tint, stream hierarchy, catchment boundary, reservoir extent, and data source/date
- [ ] Add print/export-friendly styling for static PNG/PDF map exports later, but keep v1 focused on interactive Leaflet rendering

### 8A.6 Hydrologic QA + Validation

- [ ] Compare computed catchment area for Gobind Sagar, Pong, and Thein against published basin/catchment area references
- [ ] Verify dam point placement relative to flow accumulation and reservoir outlet; correct with manual snap/override if the point falls off-network
- [ ] Check that upstream traversal includes known transboundary headwaters where hydrologically correct
- [ ] Check that flowlines terminate consistently at or upstream of each reservoir, not downstream of the dam
- [ ] Check for disconnected tributaries, reversed lines, duplicate flowlines, basin slivers, and invalid polygons
- [ ] Visually QA each reservoir map at overview, catchment, and tributary zoom levels
- [ ] Document limitations: HydroBASINS resolution, dam-not-at-outlet issue, DEM voids/errors, glacier/snow uncertainty, and rainfall/snow product limitations in high mountains

### 8A.7 Implementation Order

- [ ] Milestone 1: static selected-reservoir map with terrain, catchment boundary, dam point, reservoir extent, and major rivers
- [ ] Milestone 2: HydroBASINS sub-basin hierarchy with topology-aware hover and legend
- [ ] Milestone 3: flowline hierarchy with stream-order/upstream-area styling and zoom-dependent detail
- [ ] Milestone 4: provenance panel and QA flags surfaced in the UI
- [ ] Milestone 5: export-quality map snapshot path for reports/situation briefings
- [ ] Milestone 6: handoff to Phase 8B animated flow visualization using the validated topology and flowline layers

**Exit:** each pilot reservoir has a defensible HydroSHEDS-style hydrologic map: shaded terrain, validated upstream catchment, HydroBASINS sub-basins, hierarchical drainage network, reservoir extent, dam point, legend, provenance, and QA notes.

---

## Phase 8B — Hydrological Flow Visualization

*Goal: turn HydroBASINS/HydroSHEDS catchments from static boundaries into an explainable upstream-to-reservoir flow view showing how rainfall and snowmelt contribute to reservoir rise and release-risk.*

### 8B.1 Data Model + Contracts

- [ ] Add hydrology attribution contract for sub-basins: `area_km2`, `upstream_area_km2`, `stream_order`, `distance_to_reservoir_km`, `routing_lag_days`, `precip_24h_mm`, `precip_7d_mm`, `snow_cover_pct`, `degree_day_melt_mm_day`, `contribution_score`
- [ ] Add flowline contract for river/drainage network features clipped to each reservoir catchment
- [x] Decide v1 routing model: simple topology/routing-lag visualization first, no calibrated distributed hydrological model
- [x] Keep terminology aligned: rainfall/snowmelt are catchment-forcing features; they explain forecast/release-risk, not directly observed release events

### 8B.2 Backend Persistence

- [ ] Add `catchment_flowline` table keyed by `(reservoir_id, flowline_id)` with geometry, upstream area, stream order, downstream id, and provenance
- [ ] Add optional hydrology columns or companion table for per-sub-basin time-varying forcing summaries
- [ ] Add migration with PostGIS indexes for sub-basin and flowline geometries
- [x] Add repository queries for selected-reservoir hydrology GeoJSON — first slice: topology-derived `/geojson/flow-edges`

### 8B.3 Data Extraction Pipeline

- [ ] Clip HydroRIVERS/MERIT Hydro flowlines to each reservoir catchment
- [x] Derive sub-basin centroids and `NEXT_DOWN` topology edges from `catchment_subbasin`
- [x] Compute approximate downstream distance from each sub-basin to reservoir
- [x] Compute first-pass routing lag from distance/slope/stream order or configurable velocity assumptions — first slice uses distance / 75 km/day, clamped 0.25-7 days
- [ ] Aggregate catchment forcing per sub-basin where source resolution supports it
- [ ] Fall back honestly to catchment-level forcing when per-sub-basin forcing is unavailable

### 8B.4 API

- [ ] Add `/geojson/subbasins/hydrology?reservoir_id={rid}&date={date}` endpoint
- [ ] Add `/geojson/flowlines?reservoir_id={rid}` endpoint
- [x] Add `/geojson/flow-edges?reservoir_id={rid}&date={date}` endpoint for topology-derived animation paths — implemented as `/geojson/flow-edges` fleet collection, frontend filters by selected reservoir
- [x] Add Pydantic GeoJSON property schemas for hydrology sub-basins, flowlines, and flow edges — first slice covers sub-basins and flow edges
- [~] Add API tests for empty-data degradation, selected-reservoir filtering, and stable GeoJSON shape — flow-edge contract test added; local run skipped without DB fixture

### 8B.5 Frontend Map Layers

- [ ] Add `HydrologySubBasinLayer` choropleth for rainfall, snowmelt, antecedent precipitation index, and contribution score
- [ ] Add `FlowLineLayer` with river width proportional to upstream area / stream order
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
