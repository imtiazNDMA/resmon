# Master Implementation Plan — Reservoir Monitoring & Analytics Platform

**Version:** 1.0 · **Date:** 2026-06-16 · **Status:** Draft for review

This is the program-level plan that sequences the seven domain plans into one buildable order. It does **not** restate them — read each domain plan for detail:

| # | Track | Plan |
| --- | --- | --- |
| 01 | Infrastructure & Platform | [01-infrastructure-platform.md](01-infrastructure-platform.md) |
| 02 | Database & Data Model | [02-database-data-model.md](02-database-data-model.md) |
| 03 | Remote Sensing | [03-remote-sensing.md](03-remote-sensing.md) |
| 04 | Data Engineering | [04-data-engineering.md](04-data-engineering.md) |
| 05 | AI / ML / DL | [05-ai-ml.md](05-ai-ml.md) |
| 06 | Backend API | [06-backend-api.md](06-backend-api.md) |
| 07 | Frontend | [07-frontend.md](07-frontend.md) |

## Governing decisions (do not re-litigate)

The build is bound by the existing decision layer. Every track codes against these:

- **Frozen contracts** — [`docs/contracts/observation-and-abt.md`](../contracts/observation-and-abt.md) `contract_version: 2`: `Observation` (RS→DE), `AnalyticalBaseTable` + `ForecastForcing` (DE→ML). A column change = `contract_version` bump + cross-track notice (ADR-0003).
- **ADR-0001** — release-risk is a *transparent layer over the forecast*, not a trained classifier.
- **ADR-0002** — bulletin *Normal Storage* is the rule-curve proxy.
- **ADR-0004** — *blended* rating curve: empirical fit owns the observed range, DEM geometry supplies the near-FRL zone above observed max.
- **ADR-0005** — *closed loop*: bulletins (2015-07→2026-04) are a historical bootstrap only; production runs on SAR+DEM+forcing with no live ground truth. Accuracy is fixed by historical backtest.
- **ADR-0006** — forecaster is a pooled Δ-fill model with conformal intervals.
- **ADR-0007** — water-extraction method is chosen by a harness, per-regime robust selection, tracked in MLflow.

## Build-order spine (dependency graph)

```text
        ┌────────────────────────────────────────────────────────────┐
 P0     │ INFRA (01)  +  DB schema/core models (02)                   │  foundations
        └───────────────┬───────────────────────────┬────────────────┘
                        │                             │
 P1     ┌───────────────▼─────────────┐   (stub Observations unblock DE)
        │ DATA ENGINEERING (04):      │◀───────────────┐
        │ bulletins→ABT, forcing,     │                │
        │ ForecastForcing  → AC-10    │                │
        └───────────────┬─────────────┘                │
 P2     ┌───────────────▼─────────────┐   ┌────────────┴───────────────┐
        │ REMOTE SENSING (03):        │──▶│ real Observation rows       │
        │ S1→γ⁰→mask→area, harness    │   │ replace stubs               │
        └───────────────┬─────────────┘   └────────────────────────────┘
 P3     ┌───────────────▼─────────────────────────────┐
        │ GROUND-TRUTHING + BLENDED RATING CURVE (05): │  ← AC-2 GATE
        │ nearest-match, curve, extraction selection   │
        └───────────────┬─────────────────────────────┘
 P4     ┌───────────────▼─────────────┐
        │ ESTIMATION + FORECAST (05)  │  ← AC-3, AC-4
        └───────────────┬─────────────┘
 P5     ┌───────────────▼─────────────┐
        │ RELEASE-RISK LAYER (05)     │  ← AC-5 (primary)
        └───────────────┬─────────────┘
 P6     ┌───────────────▼─────────────┐      P7  ┌──────────────────────┐
        │ BACKEND API (06)            │─────────▶│ FRONTEND (07)        │
        │ endpoints, RBAC, alerts     │          │ map, dash, alerts    │
        │ ← AC-7, AC-9, AC-11         │          │ ← AC-6               │
        └─────────────────────────────┘          └──────────────────────┘
 P8     Full automation E2E (AC-1) · backtest+data-validation CI gates (AC-12) · observability · backups
```

**Parallelism:** Backend (06) and Frontend (07) scaffolding (auth, RBAC, app shell, typed API client against the OpenAPI/mock contract) start in **P0–P1** and proceed against fixtures; they only need real data in P6–P7. RS (P2) and DE (P1) overlap via the **stub `Observation` rule** — DE builds the ABT from stub rows so ML and serving aren't blocked on real SAR.

**Critical path:** Infra → DB → ABT(stub) → RS real extraction → ground-truthing/**AC-2** → estimation → forecast → **AC-5** → API alerts → E2E. Everything else parallelizes around it.

## Phased delivery & milestones

| Phase | Goal | Lead tracks | Exit milestone (ACs) |
| --- | --- | --- | --- |
| **P0 Foundations** | uv workspace, compose (Postgres/PostGIS, MLflow, Prefect), CI skeleton, `core/` models + Alembic, swappable `DataAccessBackend` + `FixtureBackend`, contract tests | 01, 02 | Single-command bring-up; schema migrated; CI green (AC-8 partial, AC-10 foundation) |
| **P1 Data spine** | Bulletin ingest (reuse `build_unified_dataset.py`), catchment delineation, hydromet + GFS `ForecastForcing` ingest, **ABT builder (point-in-time)** on stub Observations | 04 (+02) | ABT v1 populated, leakage-tested; data-validation gate green (**AC-10**, AC-12 partial) |
| **P2 Real SAR** | GEE client, AOI bootstrap (JRC GSW max-extent), frozen orbit/pass config, γ⁰ terrain flattening + layover/shadow masking, extraction harness → real `Observation` | 03 | Real Observations replace stubs; extraction method selected & MLflow-registered |
| **P3 Ground-truthing** | Nearest-match `GroundTruthMatch`, **blended rating curve** (ADR-0004), extraction-method validation, **AC-2 acceptance gate** | 05 (+03) | **AC-2** foundational gate passes (fill-% MAE ≤ tolerance) |
| **P4 Estimation+Forecast** | Estimation bridge (area→storage/level), pooled Δ-fill conformal forecaster, persistence+climatology baselines, walk-forward CV | 05 | **AC-3**, **AC-4** |
| **P5 Release-risk** | Release-risk layer over forecast trajectory vs FRL/threshold bands net of rule curve; episode backtest | 05 | **AC-5** (primary) |
| **P6 Serving** | FastAPI endpoints, JWT auth + RBAC, GeoJSON layers, alert generation + audit trail, Prefect admin triggers | 06 | **AC-7**, **AC-9**, **AC-11** |
| **P7 Frontend** | Leaflet map (risk-coloured), dashboard, forecast/risk panels, alerts view + ack, admin, accessibility | 07 | **AC-6** |
| **P8 Hardening** | Full automated RS→DE→ML→serve chain, backtest + data-validation CI gates, observability, backups, graceful degradation | 01 (+all) | **AC-1**, **AC-12**; all ACs closed |

## Track seams (the interfaces that must hold)

- **RS → DE:** `Observation` (frozen). RS also authors the **reservoir orbit/AOI config** the DB stores, and a DEM hypsometric-shape handoff for the blend.
- **DE → ML:** `AnalyticalBaseTable` + `ForecastForcing` (frozen). ML rating-curve fit also reads `GroundTruthMatch`.
- **ML → API:** ML persists `Prediction` + `ReleaseRisk` rows; API reads/serves them and evaluates thresholds → `Alert` (API owns generation; DB owns the table).
- **API → Frontend:** OpenAPI 3.1 contract (19 endpoints) + GeoJSON; frontend binds via a typed client.
- **Platform → all:** compose service names, env conventions, the `DataAccessBackend` ABC, CI gates.

## Cross-team decision register

Consolidated from all seven plans. **R = recommended default (architect)**; ★ = needs product/user sign-off before its phase.

| ID | Decision | Owner → affects | Recommendation | Needed by |
| --- | --- | --- | --- | --- |
| D1 ★ | **Frozen relative orbit + pass direction** for each of the 3 reservoirs | RS → DB config | RS selects from S1 coverage; store in reservoir config | P2 |
| D2 ✅ | **NFR-ACC-1 tolerance** (fill-% MAE) — gates AC-2 & all promotion | Product → ML | **RESOLVED (2026-06-16): ≤10% to start, tighten toward 5% as extraction improves** | P3 |
| D3 | **Nearest-match tolerance ±N days** (FR-GT-1) | DE/ML → RS | **±5 days** default; tune on matched-set residuals | P1/P3 |
| D4 | **GFS reforecast archive depth** covers 2015→ training window | DE | Contract asserts yes (GEE `NOAA/GFS0P25`); verify in P1, else model observed→forecast gap | P1 |
| D5 | **Water-mask storage**: raster ref vs vector geometry | RS/DB → API | Persist raster `water_mask_ref`; also store **simplified vector** for GeoJSON overlays (p95) | P2/P6 |
| D6 ✅ | **Evaporation/outflow proxy** column in `CatchmentForcing`/ABT (ML wants it for §8.3 mass balance) | ML → DE | **RESOLVED (2026-06-16): add ERA5-Land evaporation; apply as a single `contract_version: 3` bump at P1 start** | P1/P4 |
| D7 | **Per-reservoir release-threshold bands** frozen before risk levels | DB/config → ML | Derive from FRL + rule-curve proxy; store in reservoir config | P5 |
| D8 | `DATA_STALENESS_THRESHOLD_DAYS` default | Infra → API/ML/UI | **14 days** (= revisit ceiling) | P6/P7 |
| D9 | Reverse proxy / TLS | Infra → Web | **Caddy** | P0 |
| D10 | JWT signing | Backend | **HS256** for v1 | P6 |
| D11 | Risk palette (4-tier, colour-blind-safe + icon/label) | Design → Web/API | Define once; share map/badges/alerts | P7 |
| D12 | Frontend component lib / charts | Frontend | **shadcn/ui + Recharts** | P0 |
| D13 | Alert eval push vs pull | ML/API | **Both** — ML push primary, API pull safety-net | P6 |

## Acceptance-criteria coverage

AC-1 → P8 · AC-2 → P3 · AC-3 → P4 · AC-4 → P4 · AC-5 → P5 · AC-6 → P7 · AC-7 → P6 · AC-8 → P0 · AC-9 → P6 · AC-10 → P1 · AC-11 → P6 · AC-12 → P1+P8. Every AC has an owning phase.

## Immediate next actions (week 1)

1. **Resolved 2026-06-16:** D2 (AC-2 tolerance = ≤10% to start) and D6 (add evaporation, contract `v3` at P1). Remaining: **D1** (frozen orbit/pass per reservoir) — RS selects during P2.
2. **P0 kickoff in parallel:** Infra T-01 (uv workspace + skeleton) and DB T-01/T-02 (compose Postgres/PostGIS + reservoir/RBAC + PostGIS) — these unblock everyone.
3. **Stand up the `FixtureBackend`** so Backend/Frontend can scaffold against fixtures immediately.
4. **Confirm the reservoir config schema** (orbit/AOI/FRL/capacity/thresholds) jointly between RS + DB — it is referenced by 4 tracks.

## Risks & sequencing notes

- **AC-2 is the program gate.** Estimation/forecast/release work is throwaway until the blended rating curve clears AC-2 — do not let P4/P5 run ahead of a passing gate on real (non-stub) Observations.
- **Stub Observations are a scheduling tool, not a result.** Track which downstream artifacts are stub-derived so they're re-run when real SAR lands (P2).
- **Contract changes are expensive** (cross-track). Batch any ABT additions (e.g. D6 evaporation) into a single `contract_version: 3` bump rather than trickling.
- **Closed loop (ADR-0005):** there is no live ground truth in production, so "accuracy" is the historical backtest. The platform's live health signals are internal-consistency/drift, not error-vs-truth — reflect this in API/UI labelling.
