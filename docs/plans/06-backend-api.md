# 06 — Backend API Implementation Plan

**Service:** `api/` — FastAPI (Python 3.13, `uv`) REST/JSON serving layer
**Status:** Planning (no application code in this document)
**Owner:** Backend API team
**Spec:** `requirements.md` §5.5 (FR-API-1..5), §5.6 (FR-UI-6 persistence), §6.3 (Alert), §7.2/§7.4/§7.5, §3 roles
**Related:** ADR-0001 (release-risk is a layer), ADR-0003 (frozen contracts), ADR-0005 (closed loop), `docs/contracts/observation-and-abt.md`

---

## 1. Scope & owned requirements

This service is the **single serving seam** between the database/ML gold layer and the React + Leaflet frontend. It is **read-mostly** over data produced by upstream pipelines, plus it **owns** alert generation, acknowledgement, audit, and admin orchestration.

| Requirement | What this service owns |
| --- | --- |
| **FR-API-1** | Typed REST/JSON endpoints: catalogue/metadata, latest status, historical time series, forecasts, release-risk (probability/level/lead-time/factors), water-mask/GeoJSON layers, accuracy metrics, alerts, pipeline/system health |
| **FR-API-2** | Serve AOI, catchment, and water-mask geometries as Leaflet-ready GeoJSON (`FeatureCollection`) |
| **FR-API-3** | JWT auth + RBAC enforcement on protected/admin endpoints (NFR-SEC-1) |
| **FR-API-4** | Auto-generated OpenAPI 3.1 docs (`/docs`, `/redoc`, `/openapi.json`) |
| **FR-API-5** | Admin endpoints: trigger/monitor Prefect pipeline runs; manage reservoirs/AOIs/users |
| **FR-UI-6 (persistence half)** | Generate in-app alerts on release-risk threshold crossing + secondary alerts; timestamp, acknowledge, retain history |
| **NFR-REL-5** | Immutable audit trail: what was predicted/alerted, when, on which data + model version |
| **NFR-TIME-3** | `< 1 s` p95 for cached/served reads — pagination + caching + indexed queries |
| **NFR-REL-2** | Health/status endpoints; queryable pipeline run history |
| **NFR-REL-6** | Graceful degradation — serve last-known forecast-based risk with explicit staleness flags when imagery is stale |
| **NFR-SEC-2/3** | Secrets via env; HTTPS/TLS terminate at proxy; input validation (Pydantic) on every endpoint |

**Explicitly NOT owned (consume, don't compute):** SAR extraction, rating curves, forecasts, release-risk computation, ABT construction. Predictions and release-risk are **persisted by the ML pipeline** (FR-ML-5); this service reads `Prediction` / `ReleaseRisk` rows. External alert push (email/SMS/webhook) is **v2** (§2 Non-Goals) — v1 is in-app + audit only.

**Boundary on release-risk (ADR-0001):** release-risk is computed and persisted upstream as a `ReleaseRisk` row. This service **reads** it for serving and **evaluates it against per-reservoir thresholds to emit Alerts** — it does not re-derive the probability.

---

## 2. Upstream dependencies (we consume)

| Dependency | Owner | Contract / shape | Consumed how |
| --- | --- | --- | --- |
| SQLAlchemy 2.x models + Pydantic v2 schemas | DB team (`core/`) | Canonical entities §6.3; frozen `Observation`/`ABT`/`ForecastForcing` (`docs/contracts/observation-and-abt.md`, `contract_version: 2`) | Imported; we do **not** define entities |
| `Reservoir` | DB team | id, name, basin, FRL, live_capacity_bcm, AOI geom, catchment geom, rating-curve config, **release_thresholds** (level/fill-% → Watch/Warning/Imminent), seasonal rule curve | Catalogue, GeoJSON, alert thresholds |
| `Observation` | RS pipeline → DB | Contract §1 (surface_area, area_confidence, derived_volume/level, water_mask_ref, extraction_method/version, scene_ids, aoi_version) | Latest status, history, mask refs |
| `AnalyticalBaseTable` | DE pipeline → DB | Contract §2 (gt_*, surface_area, forcing, residuals, freshness_flags, row_quality) | History time series, accuracy, freshness |
| `Prediction` | ML pipeline | §6.3: reservoir_id, run_timestamp, horizon_date, predicted value(s), interval, model_version | Forecast endpoints |
| `ReleaseRisk` | ML pipeline | §6.3: release_probability, risk_level, estimated_lead_time_days, contributing_factors, model_version | Release-risk endpoints + alert source |
| `RatingCurve`, `GroundTruthMatch` | GT/DE | §6.3 | Accuracy / estimate-vs-ground-truth views |
| Backtest accuracy metrics | ML pipeline (MLflow → table) | estimation MAE, forecast skill, release recall/precision/lead-time/calibration | Accuracy endpoints (AC-5/NFR-ACC-4) |
| **Prefect** (orchestrator) | Pipelines team | Deployment IDs + Prefect API/client for `create_flow_run_from_deployment` and run-state polling | Admin trigger/monitor (FR-API-5) |
| Pipeline run history | Pipelines team | run id, flow name, status, started/finished, row counts, error | Health + admin monitor (NFR-REL-2) |

**Owned-by-us tables** (created via our own Alembic migrations within `core/` namespace, coordinated with DB team): `Alert` (§6.3), `AlertAcknowledgement` (if split), `User`/`Role`, `AuditLog` (NFR-REL-5), `RefreshToken`/token-revocation. `Alert` may be owned by DB team — **see open decision OD-1**.

---

## 3. Downstream consumers (we expose to)

- **React + Leaflet frontend** (sole consumer in v1). Drives every screen in §5.6 FR-UI-1..7: map (AOI + water-extent overlay + risk-coloured markers), KPI cards, trend/forecast charts, accuracy view, **alerts centre** (central feature), admin console.
- Consumes the **OpenAPI 3.1 contract** (§9). The generated `openapi.json` is the formal interface; a typed TS client (`openapi-typescript`) is generated from it by the frontend team.

---

## 4. Endpoint catalogue (centerpiece)

Conventions:
- Base path `/api/v1`. JSON unless noted. All list endpoints paginated (`?limit`, `?cursor` or `?page`/`?page_size`) and return `{ items, page, total }` or cursor envelope.
- Time series accept `?from=&to=` (ISO-8601 IST dates per contract) and `?reservoir_id=`.
- Reservoir id is a stable text slug (e.g. `gobind_sagar`, `pong`, `thein`).
- **Role column** = minimum role required. Hierarchy used for inheritance: `public < analyst < dam_operator < authority < admin` for *read* scope; **admin-only** marked explicitly. `public` = unauthenticated allowed.
- Roles: `authority` (Disaster-Management Authority), `dam_operator`, `analyst`, `admin`, `public`.

### 4.1 Auth & session

| Method | Path | Request (Pydantic sketch) | Response sketch | Role |
| --- | --- | --- | --- | --- |
| POST | `/auth/login` | `LoginRequest{username, password}` | `TokenPair{access_token, refresh_token, token_type="bearer", expires_in, user: UserOut}` | public |
| POST | `/auth/refresh` | `RefreshRequest{refresh_token}` | `TokenPair` | authenticated |
| POST | `/auth/logout` | `RefreshRequest{refresh_token}` | `204` (revokes refresh token) | authenticated |
| GET | `/auth/me` | — | `UserOut{id, username, email, role, display_name}` | authenticated |

### 4.2 Reservoir catalogue & metadata (FR-API-1)

| Method | Path | Request | Response sketch | Role |
| --- | --- | --- | --- | --- |
| GET | `/reservoirs` | `?basin=&q=` | `Page[ReservoirSummary]` — `{id, name, basin, frl_m, live_capacity_bcm, latest_risk_level, latest_pct_filled, last_acquisition_date, is_stale}` | public |
| GET | `/reservoirs/{id}` | — | `ReservoirDetail` — summary + `{release_thresholds:{watch,warning,imminent (level_m/pct)}, rating_curve_version, rule_curve_ref, centroid:[lon,lat]}` | public |

### 4.3 Latest status & historical time series (FR-API-1)

| Method | Path | Request | Response sketch | Role |
| --- | --- | --- | --- | --- |
| GET | `/reservoirs/{id}/status` | — | `LatestStatus{reservoir_id, as_of_date, pct_filled, live_storage_bcm, level_m, surface_area_km2, level_vs_frl_m, area_confidence, last_acquisition_date, days_since_acquisition, is_stale, freshness_flags, source:"sar"|"forecast", risk: ReleaseRiskOut}` | public |
| GET | `/reservoirs/{id}/timeseries` | `?from=&to=&fields=pct_filled,level,volume,area&include_ground_truth=true` | `TimeSeries{reservoir_id, points:[{date, pct_filled, level_m, volume_bcm, surface_area_km2, derived_*, gt_*, area_confidence, row_quality, is_extrapolated}], meta:{count, from, to}}` | public (gt fields → analyst+) |
| GET | `/reservoirs/{id}/timeseries/forcing` | `?from=&to=` | `ForcingSeries{points:[{date, catchment_precip, antecedent_precip_index, snow_cover_area, swe, degree_day_melt, freshness_flags}]}` | analyst |

> Ground-truth columns (`gt_*`) and forcing detail are analyst-trust features (FR-UI-4) — gated to `analyst+`. `public`/`authority` get the served estimate + risk only.

### 4.4 Forecasts (FR-API-1; FR-UI-3)

| Method | Path | Request | Response sketch | Role |
| --- | --- | --- | --- | --- |
| GET | `/reservoirs/{id}/forecast` | `?as_of=&metric=pct_filled` | `Forecast{reservoir_id, run_timestamp, model_version, metric, horizon:[{horizon_date, day_offset(1..14), predicted, lower, upper}], baseline:{persistence, climatology}}` | public |
| GET | `/reservoirs/{id}/forecast/runs` | `?limit=` | `Page[ForecastRunMeta{run_timestamp, model_version, horizon_days}]` | analyst |

### 4.5 Release-risk (FR-API-1; primary product output)

| Method | Path | Request | Response sketch | Role |
| --- | --- | --- | --- | --- |
| GET | `/reservoirs/{id}/release-risk` | `?as_of=` | `ReleaseRiskOut{reservoir_id, run_timestamp, release_probability(0..1), risk_level("Low"\|"Watch"\|"Warning"\|"Imminent"), estimated_lead_time_days, contributing_factors:[{name, value, unit, weight?}], model_version, forecast_run_ref, is_stale}` | public |
| GET | `/release-risk` | `?min_level=Watch` | `[ReleaseRiskOut]` (fleet snapshot, one latest per reservoir) | public |
| GET | `/reservoirs/{id}/release-risk/history` | `?from=&to=` | `Page[ReleaseRiskOut]` | analyst |

### 4.6 Geospatial GeoJSON layers (FR-API-2; FR-UI-1)

| Method | Path | Request | Response sketch | Role |
| --- | --- | --- | --- | --- |
| GET | `/reservoirs/{id}/aoi` | — | GeoJSON `Feature<Polygon>` with `properties:{aoi_version, reservoir_id}` | public |
| GET | `/reservoirs/{id}/catchment` | — | GeoJSON `Feature<Polygon>` | analyst |
| GET | `/reservoirs/{id}/water-mask` | `?date=` (default latest) | GeoJSON `Feature<Polygon\|MultiPolygon>` `properties:{acquisition_date, area_confidence, extraction_method, water_mask_ref}` | public |
| GET | `/layers/reservoirs.geojson` | `?include=risk` | GeoJSON `FeatureCollection` of all reservoir centroids/AOIs with `properties:{risk_level, pct_filled, is_stale}` for one-shot map load | public |

> GeoJSON served pre-simplified server-side (PostGIS `ST_Simplify` / `ST_AsGeoJSON`, configurable tolerance) and ETag-cached to hit NFR-TIME-3. Water-mask polygons vectorised by the RS pipeline and stored as geometry, or vectorised on read with caching — **see open decision OD-2**.

### 4.7 Accuracy & validation metrics (FR-API-1; FR-UI-4; NFR-ACC-4)

| Method | Path | Request | Response sketch | Role |
| --- | --- | --- | --- | --- |
| GET | `/accuracy/summary` | `?reservoir_id=` | `AccuracySummary{estimation_mae_pct, forecast_skill_vs_baseline, release_recall, release_precision, mean_lead_time_days, calibration, backtest_window, source:"historical_backtest", model_version}` | public |
| GET | `/reservoirs/{id}/accuracy/estimate-vs-truth` | `?from=&to=` | `[{date, derived_pct_filled, gt_pct_filled, residual, area_confidence, time_gap_days}]` (from `GroundTruthMatch`/ABT) | analyst |

### 4.8 Alerts (FR-UI-6; AC-11; owned generation + persistence)

| Method | Path | Request | Response sketch | Role |
| --- | --- | --- | --- | --- |
| GET | `/alerts` | `?reservoir_id=&type=&severity=&status=active\|acknowledged\|resolved&from=&to=` | `Page[AlertOut{id, reservoir_id, type, severity, risk_level, triggered_at, message, contributing_factors, release_risk_ref, acknowledged_by, acknowledged_at, resolved_at, status}]` | authenticated (public sees flood-release only — OD-3) |
| GET | `/alerts/{id}` | — | `AlertOut` + `audit:[AuditEntry]` | authenticated |
| POST | `/alerts/{id}/acknowledge` | `AckRequest{note?}` | `AlertOut` (sets acknowledged_by/at; writes audit) | authority, dam_operator, admin |
| POST | `/alerts/{id}/resolve` | `ResolveRequest{note?}` | `AlertOut` (sets resolved_at; audit) | authority, admin |
| GET | `/alerts/stream` | SSE | server-sent events of new/updated alerts for live alerts centre | authenticated |

> Alert **creation is system-only** (alert-generation service §6) — no public POST `/alerts`. Acknowledge/resolve are the only state-changing user actions, both audited.

### 4.9 Pipeline & system health (FR-API-1; NFR-REL-2/3)

| Method | Path | Request | Response sketch | Role |
| --- | --- | --- | --- | --- |
| GET | `/health` | — | `{status:"ok", version, db:"up", time}` (liveness, no auth) | public |
| GET | `/health/ready` | — | readiness incl. DB + Prefect reachability | public |
| GET | `/system/health` | — | `SystemHealth{api, db, last_pipeline_runs:[{pipeline, status, finished_at, freshness_lag_days}], stale_reservoirs:[id]}` | admin |
| GET | `/system/pipelines/runs` | `?pipeline=&status=&limit=` | `Page[PipelineRun{run_id, pipeline, status, started_at, finished_at, duration_s, row_counts, error, triggered_by}]` | admin |

### 4.10 Admin — pipeline orchestration (FR-API-5)

| Method | Path | Request | Response sketch | Role |
| --- | --- | --- | --- | --- |
| POST | `/admin/pipelines/{pipeline}/trigger` | `TriggerRequest{reservoir_id?, params?}` (`pipeline` ∈ remote_sensing\|data_engineering\|ml_inference) | `PipelineRun{run_id, status:"scheduled", prefect_flow_run_id}` | admin |
| GET | `/admin/pipelines/runs/{run_id}` | — | `PipelineRun` (live status proxied from Prefect) | admin |
| POST | `/admin/pipelines/runs/{run_id}/cancel` | — | `PipelineRun` | admin |

### 4.11 Admin — reservoir / AOI / user management (FR-API-5)

| Method | Path | Request | Response sketch | Role |
| --- | --- | --- | --- | --- |
| POST | `/admin/reservoirs` | `ReservoirCreate{id, name, basin, frl_m, live_capacity_bcm, dam_point:[lon,lat], release_thresholds, rule_curve_ref}` | `ReservoirDetail` | admin |
| PATCH | `/admin/reservoirs/{id}` | `ReservoirUpdate{partial}` (thresholds, capacity, rating-curve config) | `ReservoirDetail` | admin |
| PUT | `/admin/reservoirs/{id}/aoi` | GeoJSON `Feature<Polygon>` + `{note}` | `{aoi_version, accepted}` (manual override, FR-RS-1) | admin |
| PUT | `/admin/reservoirs/{id}/catchment` | GeoJSON `Feature<Polygon>` | `{catchment_version}` (override, FR-DE-7) | admin |
| GET | `/admin/users` | `?role=` | `Page[UserOut]` | admin |
| POST | `/admin/users` | `UserCreate{username, email, role, password}` | `UserOut` | admin |
| PATCH | `/admin/users/{id}` | `UserUpdate{role?, active?, password?}` | `UserOut` | admin |
| DELETE | `/admin/users/{id}` | — | `204` (soft-deactivate) | admin |

### 4.12 Export (FR-UI-5)

| Method | Path | Request | Response | Role |
| --- | --- | --- | --- | --- |
| GET | `/reservoirs/{id}/export.csv` | `?from=&to=&fields=` | `text/csv` time series | analyst |
| POST | `/reports/situation` | `ReportRequest{reservoir_ids, from, to}` | `application/pdf` situation report | authority, admin |

---

## 5. Auth / RBAC design

- **Auth scheme:** JWT bearer (OAuth2 password flow shape for OpenAPI). Short-lived **access token** (~15 min, `HS256` or `RS256` — OD-4) carrying `sub`, `role`, `exp`, `jti`. Long-lived **refresh token** (rotating, persisted hashed in `RefreshToken` table for revocation). Passwords hashed with `argon2` (via `passlib`/`argon2-cffi`).
- **Role model:** single-role-per-user enum `{public, analyst, dam_operator, authority, admin}` stored on `User`. (Multi-role is a v2 concern; one role keeps RBAC checks O(1).)
- **Enforcement:** a FastAPI dependency `require_role(min_role)` / `require_any({...})` resolved per route. Read endpoints use an ordered-rank check; admin endpoints require exact `admin`. `public` endpoints use an `optional_user` dependency so they work unauthenticated but can enrich for logged-in users.
- **Field-level gating:** `gt_*` / forcing / catchment / accuracy-detail responses are projected by role in the serializer (analyst+ sees ground-truth; public/authority sees served estimate only) — implemented as response-model selection, not row filtering, to keep caching keys role-bucketed.
- **Defence:** input validation entirely via Pydantic v2 (NFR-SEC-3); rate-limit `/auth/login` (slowapi); CORS locked to the frontend origin; security headers middleware; TLS terminated at the reverse proxy (NFR-SEC-3). Secrets (JWT key, DB DSN, Prefect API key) from env / secret store (NFR-SEC-2).
- **Every state-changing call** (`acknowledge`, `resolve`, admin mutations, pipeline triggers) records actor + action in `AuditLog`.

**Role → capability matrix (summary, aligns §3):**

| Capability | public | analyst | dam_operator | authority | admin |
| --- | --- | --- | --- | --- | --- |
| View public status/map/risk | ✓ | ✓ | ✓ | ✓ | ✓ |
| Forecast charts | ✓ | ✓ | ✓ | ✓ | ✓ |
| Ground-truth / accuracy detail / water masks detail | | ✓ | ✓ | ✓ | ✓ |
| View alerts (all types) | flood only | ✓ | ✓ | ✓ | ✓ |
| Acknowledge alerts | | | ✓ | ✓ | ✓ |
| Resolve alerts | | | | ✓ | ✓ |
| Export CSV / situation report | | csv | csv | ✓ | ✓ |
| Trigger/monitor pipelines | | | | | ✓ |
| Manage reservoirs/AOIs/users | | | | | ✓ |

---

## 6. Alert-generation & audit design

### 6.1 Generation trigger (AC-11, FR-UI-6, ADR-0001)

The **alert-generation service** is an internal module invoked **after each ML inference refresh persists a new `ReleaseRisk`/`Prediction`** (FR-ML-5). Two invocation paths, support both:
- **Push (preferred):** the ML/inference Prefect flow, on completing a refresh, calls `POST /internal/alerts/evaluate` (service-token auth, not in public OpenAPI) for the affected reservoir, OR
- **Pull (fallback / safety net):** a lightweight scheduled evaluator (APScheduler in-process or a Prefect tick) scans for `ReleaseRisk` rows newer than the last evaluation watermark.

Choice tracked as **OD-5**; design supports both so a missed push is still caught by the pull sweep.

### 6.2 Evaluation logic

For each new `ReleaseRisk` row, compare against the reservoir's persisted `release_thresholds` and recent state:

1. **Flood-release alert** — `risk_level` transitions **upward** into `Watch`/`Warning`/`Imminent` (threshold *crossing*, not mere presence — dedupe against the last open alert of same type so a sustained Warning does not re-fire every cycle). Severity maps from risk_level.
2. **Approaching-FRL** — derived level/pct within configured margin of FRL even if risk model is lower.
3. **Rapid-rise** — rate-of-change of `pct_filled` over recent acquisitions exceeds threshold.
4. **Data-quality / stale** — `days_since_acquisition` exceeds staleness bound, or `row_quality = quarantine`, or extraction confidence collapse (supports NFR-REL-6 graceful-degradation signalling).

Each fired alert is **idempotent**: keyed on `(reservoir_id, type, triggering_run_timestamp)` so re-running the evaluator never duplicates. A new alert is created only on a **new crossing** or new run; an existing unresolved alert of the same `(reservoir, type)` is **updated** (escalated severity) rather than duplicated.

### 6.3 Persistence (Alert entity §6.3)

Write to `Alert`: `reservoir_id, type, severity, triggered_at, message, contributing_factors (copied from ReleaseRisk for point-in-time immutability), release_risk_ref (FK to the exact ReleaseRisk row), acknowledged_by/at, resolved_at`. `message` is a generated human string ("Pong: Warning — forecast fill 96% vs FRL within 3 days; lead time 4d"). History is the full `Alert` table (FR-UI-6: timestamped, acknowledgeable, retained).

### 6.4 Audit trail (NFR-REL-5)

Separate **append-only** `AuditLog` table — never updated/deleted:
`{id, ts, actor (user id or "system"), action, entity_type, entity_id, model_version, data_version (abt_version/run_timestamp), payload_snapshot (jsonb), ip}`.
Written for: every alert generated (records *what was alerted, when, on which data + model version* — the NFR-REL-5 obligation), every acknowledge/resolve, every admin mutation, every pipeline trigger. Because alerts copy `contributing_factors` + `release_risk_ref` + `model_version` at creation, the audit answers "what did we warn, on what evidence" even after upstream rows change. Enforce immutability via DB grants (no UPDATE/DELETE for the app role) and/or trigger.

---

## 7. Task breakdown (sequenced)

Each task lists acceptance checks. T-01..T-04 are foundational; later tasks parallelise.

| ID | Task | Acceptance check |
| --- | --- | --- |
| **T-01** | Scaffold `api/` (uv project, FastAPI app, settings via `pydantic-settings`, structured logging, `/health`, Dockerfile). Wire `core/` models as a dependency. | App boots; `GET /health` → 200; `/openapi.json` served; container builds |
| **T-02** | DB session layer (async SQLAlchemy 2.x, connection pool), read-only repository pattern over `core/` models; pagination + `from/to` query helpers. | Integration test reads a seeded `Reservoir`; paginated list returns envelope |
| **T-03** | Auth: `User`/`RefreshToken` migrations (coordinated w/ DB team), `/auth/*`, JWT issue/verify, `argon2` hashing, `require_role` deps. | Login returns token pair; protected route 401 without token, 403 wrong role; refresh rotates |
| **T-04** | RBAC matrix wiring + role-projected response models; CORS, security headers, login rate-limit. | Each row of §5 matrix covered by a test (allow/deny); `gt_*` hidden from public |
| **T-05** | Reservoir catalogue + metadata endpoints (§4.2) reading `Reservoir`. | `/reservoirs`, `/reservoirs/{id}` match schema; thresholds present |
| **T-06** | Latest status + time-series + forcing endpoints (§4.3) over `Observation`/`ABT`; freshness + `source` + `is_stale` logic (NFR-REL-6). | Status returns `source:"forecast"` + `is_stale:true` when acquisition stale; series honours `from/to/fields` |
| **T-07** | Forecast endpoints (§4.4) over `Prediction`; baseline fields. | 14-horizon payload with intervals + baseline; `?as_of` selects run |
| **T-08** | Release-risk endpoints (§4.5) over `ReleaseRisk`; fleet snapshot. | Risk payload incl. contributing_factors, lead_time; fleet endpoint one-per-reservoir |
| **T-09** | GeoJSON layers (§4.6): AOI/catchment/water-mask + combined FeatureCollection; PostGIS `ST_AsGeoJSON`/`ST_Simplify`; ETag caching. | Valid GeoJSON (schema-validated), renders in Leaflet sandbox; ETag 304 on repeat |
| **T-10** | Accuracy endpoints (§4.7) over backtest metrics + `GroundTruthMatch`/ABT. | Summary marks `source:"historical_backtest"`; estimate-vs-truth residuals returned |
| **T-11** | `Alert`/`AuditLog` migrations + alert-generation service (§6): evaluation logic, idempotent dedupe, persistence. | Threshold-crossing fixture → exactly one Alert + one AuditLog; re-run → no duplicate |
| **T-12** | Alert API (§4.8): list/get/acknowledge/resolve + SSE stream; audit on state changes. | Acknowledge sets fields + writes audit; SSE delivers new alert; filters work |
| **T-13** | Internal `/internal/alerts/evaluate` (service-token) + scheduled pull evaluator (APScheduler). | Push call generates alert; pull sweep catches an un-pushed ReleaseRisk |
| **T-14** | Health/system endpoints (§4.9) + pipeline run history reads. | `/system/health` shows last runs + stale reservoirs; admin-gated |
| **T-15** | Admin pipeline orchestration (§4.10) via Prefect client (`create_flow_run_from_deployment`, run polling, cancel). | Trigger returns prefect_flow_run_id; status proxied; non-admin 403; audited |
| **T-16** | Admin reservoir/AOI/catchment/user management (§4.11). | Create/patch reservoir; AOI override bumps `aoi_version`; user CRUD role-gated |
| **T-17** | Export (§4.12): CSV stream + PDF situation report. | CSV matches series; PDF generated for authority |
| **T-18** | Caching layer (ETag + short-TTL in-process/Redis for hot reads) + DB index review for p95. | Load test: served reads p95 < 1 s (NFR-TIME-3) |
| **T-19** | OpenAPI polish (tags, examples, security schemes, descriptions) + publish `openapi.json` artifact for frontend. | `/docs` renders all tags; generated TS client compiles |
| **T-20** | Test suite + CI wiring (NFR-TEST-2): unit + integration + contract tests. | CI green; coverage gate; RBAC matrix tests pass |

---

## 8. Interfaces / contracts we expose

The **OpenAPI 3.1 contract** generated by FastAPI is the formal interface; `openapi.json` is published as a build artifact and consumed by the frontend (`openapi-typescript` → typed client). Stable surface the frontend depends on:

- **Read surface** (public→analyst): §4.2–§4.7 (catalogue, status, timeseries, forecast, release-risk, geojson, accuracy).
- **Alerts surface**: §4.8 incl. SSE `/alerts/stream`.
- **Admin surface**: §4.9–§4.12.
- **Auth surface**: §4.1 OAuth2-password security scheme advertised in OpenAPI.

Key payload shapes the frontend binds to (frozen names): `ReservoirSummary`, `ReservoirDetail`, `LatestStatus`, `TimeSeries`/point, `Forecast`/horizon-point, `ReleaseRiskOut` (`risk_level` enum `Low|Watch|Warning|Imminent`), GeoJSON `Feature`/`FeatureCollection` with documented `properties`, `AlertOut` (`type` enum `flood-release|approaching-FRL|rapid-rise|data-quality`; `status` enum `active|acknowledged|resolved`), `AccuracySummary`, `PipelineRun`, `UserOut`. Enums and units are part of the contract and must not silently change (mirrors ADR-0003 discipline for the API seam).

---

## 9. Library choices

| Concern | Choice | Why |
| --- | --- | --- |
| Web framework | **FastAPI** | Mandated (§4.2); native OpenAPI, Pydantic v2, async |
| Server | **uvicorn** (+ gunicorn workers in prod) | Standard ASGI |
| ORM / DB | **SQLAlchemy 2.x async** + **asyncpg**; **GeoAlchemy2** for PostGIS | Mandated stack; geometry support |
| Schemas | **Pydantic v2** + **pydantic-settings** | Mandated; validation/serialization, env config |
| Migrations | **Alembic** (for app-owned tables only) | Coordinated with DB team |
| Auth | **python-jose**/**pyjwt** + **passlib[argon2]** / **argon2-cffi** | JWT + secure hashing |
| Rate limit | **slowapi** | Login throttling |
| Orchestration client | **prefect** client SDK | Trigger/monitor deployments (FR-API-5) |
| Caching | **ETag** middleware + optional **Redis** (`redis-py`) for hot reads | NFR-TIME-3 |
| Geo serialization | **PostGIS** `ST_AsGeoJSON`/`ST_Simplify` (in-DB) | Fast Leaflet-ready output |
| PDF/CSV | **WeasyPrint**/**reportlab** (PDF), stdlib `csv` streaming | Reports/export (FR-UI-5) |
| Testing | **pytest**, **pytest-asyncio**, **httpx** ASGITransport, **testcontainers**/**pytest-postgresql** | Unit + integration |
| Lint/format | **ruff**, **mypy** | Quality gate |

---

## 10. Testing strategy

- **Unit:** RBAC dependency logic, JWT issue/verify/expiry/revocation, alert-evaluation decision table (each alert type + dedupe/idempotency), freshness/`is_stale` logic, role-projected serializers.
- **Integration (real Postgres+PostGIS via testcontainers):** every endpoint against seeded data — pagination, `from/to`, GeoJSON validity, status `source` switching, forecast/risk shapes. Alert-generation end-to-end: insert `ReleaseRisk` crossing → exactly one `Alert` + `AuditLog`; re-run → no dup; acknowledge/resolve writes audit (**covers AC-11**).
- **Contract:** validate responses against the published Pydantic/OpenAPI schemas; snapshot `openapi.json` to catch breaking changes (ADR-0003 discipline).
- **RBAC matrix:** parametrised allow/deny test for every (role × endpoint) cell in §5 (**covers AC-9**).
- **Performance:** load test served read endpoints; assert p95 < 1 s with caching + indexes (NFR-TIME-3).
- **Prefect:** mock the Prefect client for trigger/monitor; one integration smoke against a Prefect test server.
- **CI (NFR-TEST-2):** ruff + mypy + pytest on every change.

---

## 11. Risks & open decisions

**Risks**
- **R1 — Schedule coupling on `core/` models:** we cannot finish read endpoints until DB team freezes models. *Mitigation:* code against the frozen contract (`observation-and-abt.md`) + entity list §6.3; use stub/synthetic rows (contract §1 stub rule) to unblock; thin repository layer isolates model churn.
- **R2 — Release-risk persistence timing:** if ML doesn't persist `ReleaseRisk` reliably, alerts won't fire. *Mitigation:* pull-sweep evaluator (§6.1) as safety net; staleness alert flags missing refresh.
- **R3 — Water-mask vectorisation cost** (OD-2) could blow the p95 budget if done on read. *Mitigation:* prefer RS pipeline persisting vector geometry; cache + simplify.
- **R4 — Prefect coupling** for admin triggers; API of deployment IDs must be agreed. *Mitigation:* config-driven deployment-id map; degrade trigger endpoint gracefully if Prefect down.
- **R5 — Audit immutability** must be enforced at DB grant level, not just app code, to satisfy NFR-REL-5.

**Open decisions (affect other teams)**
- **OD-1 (DB team):** Who owns the `Alert` table migration — DB team (it's in §6.3 canonical entities) or this service? We need write access regardless. *Proposal:* DB team defines the model in `core/`; we own generation logic + acknowledge/resolve.
- **OD-2 (RS pipeline):** Are water masks persisted as **vector geometry** (PostGIS) or only raster refs (`water_mask_ref`)? Vector is required for `/water-mask` GeoJSON without per-request vectorisation. *Proposal:* RS pipeline persists simplified vector polygon alongside the raster ref.
- **OD-3 (product/authority):** What exactly does a **public** viewer see in `/alerts`? *Proposal:* flood-release alerts only (Watch+), no data-quality/admin alerts.
- **OD-4 (security):** JWT signing `HS256` (shared secret) vs `RS256` (asymmetric, better if other services verify). *Proposal:* `HS256` for v1 single-service simplicity.
- **OD-5 (ML/pipelines):** Alert evaluation **push** (ML flow calls us) vs **pull** (we sweep). *Proposal:* implement both; push primary, pull as watermark safety net.
- **OD-6 (pipelines):** Stable Prefect **deployment IDs** and run-history table shape for `/system/pipelines/runs` and admin triggers.

---

## 12. Mapping to acceptance criteria

| AC | How this service satisfies it |
| --- | --- |
| **AC-6** (dashboard renders map, risk, alerts, KPI, charts, accuracy) | We serve every data feed the UI needs: `/layers/reservoirs.geojson` + `/aoi` + `/water-mask` (map), `/release-risk` (risk indicators), `/alerts` + SSE (early-warning centre), `/status` (KPI cards), `/timeseries` + `/forecast` (trend/forecast charts), `/accuracy/*` (comparison). |
| **AC-7** (new SAR reflected within SLA, freshness shown, risk refreshed each acquisition) | `LatestStatus` exposes `last_acquisition_date`, `days_since_acquisition`, `is_stale`, `freshness_flags`, `source`; risk endpoint reflects the latest persisted refresh; graceful degradation (NFR-REL-6) serves forecast-based risk when imagery is stale. |
| **AC-9** (RBAC, logging, health monitoring, backups operational) | JWT + RBAC matrix (§5), structured logging, `/health`+`/system/health` + pipeline-run history (§4.9). (DB backups owned by ops/infra — we expose health, not backup execution.) |
| **AC-11** (in-app alert on threshold crossing, timestamped acknowledgeable history, audit NFR-REL-5) | Alert-generation service (§6) fires idempotently on risk-level crossing, persists to `Alert` with timestamps + ack/resolve, writes immutable `AuditLog` recording what/when/which-data/model-version. |
