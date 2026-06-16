# Reservoir Monitoring & Analytics Platform — Requirements Specification

**Document type:** Production product specification
**Version:** 1.2
**Last updated:** 2026-06-16
**Status:** Draft for review

---

## 1. Overview & Vision

The **Reservoir Monitoring & Analytics Platform** is a full-stack **disaster-management** web application. Its single, primary purpose is to **monitor reservoirs and predict the likelihood of a water release** — so that downstream communities and authorities receive early warning before a controlled or emergency release (spillway/sluice discharge) that could cause flooding.

The platform uses **Sentinel-1 Synthetic Aperture Radar (SAR)** satellite imagery and a **Digital Elevation Model (DEM)** to track each reservoir's storage, and presents the resulting **release-risk outlook** through a modern, interactive dashboard and real-time map.

The platform automatically and continuously:

1. **Detects** the water surface area of each monitored reservoir from radar imagery (cloud- and weather-immune).
2. **Derives** the stored water volume and fill level by combining detected surface area with a DEM-derived hypsometric (area–elevation–volume) curve.
3. **Validates** these estimates against historical ground-truth records from official reservoir bulletins.
4. **Forecasts** near-term (1–14 day) reservoir fill levels and the **probability of a release** as the forecast level approaches Full Reservoir Level (FRL).
5. **Warns** stakeholders via the dashboard, real-time map, and alerts, prioritising lead time before a likely release.

### Value proposition

Disaster-management authorities, dam operators, and downstream stakeholders gain a single, always-current, weather-independent view of reservoir storage and **how close each reservoir is to a release** — turning what is usually a last-minute manual decision into an early, data-driven flood-risk warning with days of lead time. Because monitoring relies on radar rather than optical imagery, the early-warning signal **survives exactly the cloudy, monsoon conditions when release risk is highest**.

### Pilot fleet (initial scope)

The system targets the reservoirs already present in the project's historical dataset (Northern India / BBMB-monitored set):

| Reservoir | River basin | Notes |
| --- | --- | --- |
| **Gobind Sagar (Bhakra Dam)** | Sutlej | Primary irrigation + hydropower |
| **Pong Dam** | Beas | Irrigation + hydropower |
| **Thein Dam (Ranjit Sagar)** | Ravi | Irrigation + hydropower |

The architecture must be **configuration-driven** so additional reservoirs can be onboarded by adding an Area-of-Interest (AOI) polygon and rating-curve configuration — without code changes.

---

## 2. Goals & Non-Goals

### Goals

- **Predict the likelihood of a reservoir water release** (the primary objective) with enough lead time to act, and communicate it as a clear release-risk level per reservoir.
- Automated, end-to-end pipeline from satellite acquisition to release-risk warning, requiring no routine manual intervention.
- Accurate surface-area, volume, and fill-level estimates validated against ground truth (these feed the release prediction).
- Short-term (1–14 day) fill-level forecasting as the basis for release-risk estimation.
- A modern, clean, professional, responsive web UI with a real-time map, analytics dashboard, and an early-warning alerting view.
- Reproducible, observable, and containerised deployment.

### Non-Goals (explicitly out of scope for v1)

- Optical (Sentinel-2 / NDWI) imagery fusion — SAR + DEM only. *(Candidate for v2.)*
- Long-range (seasonal / annual) forecasting — short-term only.
- Global / arbitrary reservoir coverage — limited to the configured pilot fleet.
- Sediment/bathymetry surveying or dam structural monitoring.
- Public mobile-native apps (the responsive web app serves mobile browsers).
- **Full physically-based / distributed hydrological modelling** (e.g. SWAT, VIC). Precipitation and snowmelt enter as **engineered catchment-forcing features**, not a calibrated process model. *(Conceptual inflow model is a candidate for v2.)*
- **Paid datasets or paid software** — the platform is open-data/open-source only (see §4.4).
- **External alert delivery** (email/SMS/webhook push to outside systems) — v1 surfaces and persists alerts **in-app** only (dashboard + audit history); outbound notification channels are a v2 candidate.

---

## 3. Stakeholders & User Roles

| Role | Description | Key capabilities |
| --- | --- | --- |
| **Disaster-Management Authority** | Emergency-response decision-maker (primary user) | Monitor release-risk levels, receive early-warning alerts, view affected areas, export situation reports |
| **Dam Operator / Water Resource Manager** | Operates the reservoir and authorises releases | View live status, forecasts, release-risk outlook; corroborate against operational data |
| **Data / Remote-Sensing Analyst** | Investigates trends and model quality | Drill into time series, compare estimate vs ground truth, inspect water masks, review prediction accuracy |
| **Administrator** | Operates the platform | Manage reservoirs/AOIs, trigger/monitor pipelines, manage users, view system health |
| **Public / Read-only Viewer** | Downstream public / general audience | View public release-risk status and map (no admin or export controls) |

Access is governed by **role-based access control (RBAC)** (see §7.5).

---

## 4. System Architecture

### 4.1 High-level design

The platform is composed of **three automated data pipelines** feeding a **serving layer** (API + web app), deployed as containerised services. Data flows through a **medallion-style** progression (raw → refined → analytics-ready → served).

```
                          ┌─────────────────────────────────────────────┐
                          │            COMPUTE: HYBRID                    │
                          │  Google Earth Engine (heavy SAR/DEM)  +       │
                          │  Self-hosted services (API, DB, ML, UI)       │
                          └─────────────────────────────────────────────┘

  ┌──────────────────┐    ┌───────────────────┐    ┌────────────────────┐
  │ 1. REMOTE SENSING │   │ 2. DATA ENGINEERING│   │ 3. AI / DL / ML     │
  │   PIPELINE        │──▶ │   PIPELINE (ETL)   │──▶│   PIPELINE          │
  │                   │    │                   │    │                    │
  │ Sentinel-1 + DEM  │    │ clean • validate  │    │ estimation +       │
  │ → water mask      │    │ fuse • ground-     │    │ forecasting        │
  │ → surface area    │    │ truth • load       │    │ (MLflow-tracked)   │
  │ (GEE / geemap)    │    │ (Python, UV)      │    │                    │
  └──────────────────┘    └─────────┬─────────┘    └─────────┬──────────┘
         (BRONZE→SILVER)            │  (SILVER→GOLD)         │ (GOLD→SERVING)
                                    ▼                        ▼
                          ┌─────────────────────────────────────────────┐
                          │   PostgreSQL + PostGIS (geometry + metrics)  │
                          │   MLflow registry (models + artifacts)       │
                          └───────────────────────┬─────────────────────┘
                                                  │
                                    ┌─────────────▼─────────────┐
                                    │   FastAPI  (REST/JSON API) │
                                    └─────────────┬─────────────┘
                                                  │
                                    ┌─────────────▼─────────────┐
                                    │  React + Leaflet dashboard │
                                    └───────────────────────────┘
```

### 4.2 Technology stack (mandated)

| Layer | Technology | Responsibility |
| --- | --- | --- |
| Satellite & geodata processing | **Google Earth Engine** via **`geemap`** + **`xee`** | Server-side EE access (`geemap`) and pulling EE collections into `xarray` for time-series/ML feature extraction (`xee`): Sentinel-1, DEM/hydrography, catchment basins, precip/snow/temperature, and forecast forcing |
| Hydromet datasets (all open, all in GEE) | CHIRPS / GPM IMERG / ERA5-Land (precip, temp, SWE, snowmelt), GLDAS (SWE, snowmelt), MODIS snow cover, **NOAA GFS** (forecast precip + temperature), HydroSHEDS **HydroBASINS** + MERIT Hydro (catchments) | Catchment-forcing features for inflow-aware forecasting — full catalogue in §6.6 |
| Python env / packaging | **`uv`** | Fast, reproducible dependency & virtual-env management for all Python services |
| ETL / pipelines | **Python** (orchestrated) | Cleaning, validation, fusion, ground-truthing, loading |
| ML lifecycle | **MLflow** | Experiment tracking, model registry, metrics, model serving/versioning |
| Database | **PostgreSQL + PostGIS** | Spatial geometries (AOI, water masks) + time-series metrics + app data |
| Backend API | **FastAPI** | Typed REST/JSON API, auth, serving estimates/forecasts to the frontend |
| Frontend | **React** + **Leaflet** | Real-time map, dashboard, charts, admin UI |
| Packaging / deploy | **Docker** + Docker Compose | Containerised, reproducible multi-service deployment |

### 4.3 Pipeline automation

All three pipelines run **fully automated** on a schedule/trigger with no routine manual steps:

- A **scheduler/orchestrator** (e.g. cron-style scheduled jobs or a lightweight orchestrator such as APScheduler/Prefect running in a container) triggers the Remote Sensing pipeline aligned to the Sentinel-1 revisit cadence (~6–12 days) and re-checks for newly published scenes daily.
- Each successful Remote Sensing run **automatically triggers** the downstream Data Engineering run, which on success triggers ML inference/forecast refresh.
- All jobs are **idempotent** (safe to re-run; upserts keyed by reservoir + acquisition date) and **observable** (status, duration, row counts, and failures are logged and surfaced to admins).

### 4.4 Open-source & free-data constraint

- The platform shall rely **exclusively on open datasets and open-source tooling** — **no paid datasets and no paid software**. All satellite, DEM, precipitation, snow, temperature, and catchment data must come from open sources (e.g. Copernicus/Sentinel, NASA, ERA5, MODIS, HydroSHEDS).
- **Google Earth Engine caveat:** GEE's *data catalogue* is free, but the platform itself is free **only for research / non-commercial use** — commercial production requires a paid licence. GEE/`geemap` is used here under the **non-commercial tier**. To preserve a fully-free path, the data-access layer should be kept **thin and swappable** so it can migrate to a fully-open backend (Copernicus Data Space Ecosystem / openEO, Microsoft Planetary Computer, SNAP, direct download) without rewriting downstream pipelines if/when the product is commercialised. *(This is the one known licensing dependency and is documented deliberately.)*

---

## 5. Functional Requirements

### 5.1 Remote Sensing Pipeline (FR-RS)

- **FR-RS-1** — For each configured reservoir AOI, retrieve the latest available Sentinel-1 GRD scene(s) intersecting the AOI via GEE/`geemap`. To keep the area time series physically comparable, **fix the acquisition geometry per reservoir** (consistent relative orbit and pass direction — ascending *or* descending), or normalise for incidence angle when scenes must be mixed. The AOI must be sized to the reservoir's **maximum (FRL) extent**, including upstream arms/tails, so high-water states are never clipped. **AOI provenance (v1):** derive each AOI reproducibly from the **JRC Global Surface Water** max-extent layer (`JRC/GSW1_4/GlobalSurfaceWater`) — threshold historical max-water occurrence, take the connected component containing the dam point (the three dam-point coordinates are seed config), buffer modestly, clip to a generous FRL-sized envelope including upstream arms — then review each of the three buffered AOIs by eye once before freezing. Persist as versioned GeoJSON config → PostGIS, with manual override per reservoir.
- **FR-RS-2** — Apply SAR preprocessing required for water detection — calibration to backscatter, speckle filtering, **radiometric terrain flattening (gamma-0)** and **DEM-based layover/shadow masking** (essential in the steep Himalayan terrain of the pilot fleet) — then produce a binary **water mask** clipped to the AOI using a **machine-learning-based water-extraction method**: unsupervised clustering (e.g. K-means / Gaussian-mixture / Otsu on backscatter, typically VH-dominant) and/or trained image segmentation (e.g. Random-Forest pixel classifier or U-Net), rather than a single fixed global threshold. The extraction method is pluggable and versioned.
- **FR-RS-3** — Compute **water surface area** (km²/ha) from the water mask using a true-area measure (`ee.Image.pixelArea()` / an equal-area projection — never raw lat/long pixel counts). Each area value carries a quality/confidence indicator (e.g. cluster separability, mask compactness, fraction of AOI under layover/shadow).
- **FR-RS-4** — Derive **stored volume** and **fill level** by intersecting the water extent with the **DEM-derived hypsometric (area–elevation–volume) curve** for that reservoir.
- **FR-RS-5** — Persist per-acquisition results (date, area, derived volume, derived level, scene metadata, water-mask reference) and emit a downstream trigger.
- **FR-RS-6** — Record provenance for every estimate (scene IDs, processing parameters, AOI version) for auditability and reproducibility.

### 5.2 Data Engineering Pipeline (FR-DE)

- **FR-DE-1** — Ingest historical ground-truth bulletin time series (reservoir, date, FRL, current level, live capacity, current live storage in BCM, `pct_filled`, benefits) and load into the gold schema.
- **FR-DE-2** — Clean & standardise units, reservoir names, and dates; deduplicate; reject/quarantine malformed records.
- **FR-DE-3** — **Fuse** satellite-derived estimates with ground-truth records on (reservoir, nearest date) to build a unified, analytics-ready time series.
- **FR-DE-4** — Apply **data-quality gates** (range/consistency checks, e.g. fill % within 0–110%, area non-negative, level ≤ FRL within tolerance); flag anomalies.
- **FR-DE-5** — Compute the **estimate-vs-ground-truth residuals** used for accuracy reporting and model validation.
- **FR-DE-6** — Load curated outputs into PostgreSQL via **idempotent upserts**; maintain a load/audit log.

**Catchment hydrometeorological feature generation** (drives inflow-aware forecasting & release prediction; all sources open):

- **FR-DE-7 (Catchment delineation)** — For each reservoir, obtain the **true upstream contributing area to the dam point** by tracing **MERIT Hydro** flow accumulation (`upa`) / `pyflwdir` from the dam, using **HydroSHEDS HydroBASINS** (`WWF/HydroSHEDS/v1/Basins/hybas_*`) only as coarse scaffold — the dam rarely sits at a basin outlet, so a single-polygon containment pick over/under-counts. Validate the delineated area against published basin areas. Note the pilot catchments are **large, high-altitude, and transboundary** (the Sutlej above Bhakra reaches into Tibet). Persist the catchment polygon (PostGIS). Done once per reservoir, re-runnable on config change, with manual-override support.
- **FR-DE-8 (Precipitation ingestion & aggregation)** — Ingest open precipitation via `geemap`/`xee` and compute **catchment-aggregated precipitation** per time step, plus engineered features: lagged precip and an **antecedent precipitation index** capturing routing delay between rainfall and reservoir response. **Product priority for these high-altitude transboundary catchments: ERA5-Land leads** (cloud-free reanalysis, altitude-robust, co-located with its SWE/snowmelt/temperature), **GPM IMERG** as the satellite cross-check, **CHIRPS demoted to a tertiary cross-check** (weak at high altitude / blind to snowfall here).
- **FR-DE-9 (Snow & temperature ingestion)** — Ingest open **snow-cover area** (MODIS NDSI), **SWE / snowmelt** and **2 m temperature** (ERA5-Land and/or GLDAS) over the catchment; compute **degree-day melt potential** (temperature-index) and snow-cover-area trend as **snowmelt features**.
- **FR-DE-10 (Forecast forcing)** — Ingest **NOAA GFS** (`NOAA/GFS0P25`, 16-day forecast) aggregated over the catchment: **forecast precipitation** and **forecast 2 m temperature** (the latter driving a **forecast degree-day melt** term), providing forward-looking drivers across the full 1–14 day horizon.
- **FR-DE-11** — Assemble a per-reservoir, per-date **catchment-forcing feature table** (precip, antecedent index, snow-cover area, SWE, degree-day melt, forecast precip), time-aligned to the storage time series, with provenance and data-freshness flags; load via idempotent upserts.
- **FR-DE-12** — Produce the **Unified Analytical Base Table (§6.7)** as the Data-Engineering pipeline's gold output — joining the fused storage/ground-truth series (FR-DE-3) with the catchment-forcing table (FR-DE-11) per the ABT requirements (FR-ABT-1…5). This is the single dataset consumed by the ML pipeline.

### 5.3 Ground-Truthing & Calibration Workflow (FR-GT) — foundational

This workflow runs **first**, before forecasting/release prediction can be trusted. It establishes that the ML-extracted surface area is consistent with the historical ground-truth record, and it calibrates the area→volume→level relationship used everywhere downstream.

- **FR-GT-1 (Temporal nearest-match)** — For every historical ground-truth record (reservoir, date), find the **nearest available Sentinel-1 acquisition** over that AOI. Reject any pairing whose acquisition–bulletin time gap exceeds a configurable tolerance (e.g. **±N days**), and record the actual gap with each pair.
- **FR-GT-2 (ML extraction on matched scenes)** — Extract the **water surface area** from each matched scene using the ML-based water-extraction method (FR-RS-2: clustering / image segmentation), producing area + a confidence/quality measure.
- **FR-GT-3 (Indirect validation against ground truth)** — Because bulletins record level/volume (not area), convert each extracted area through the DEM **hypsometric (area→volume→level) curve** and compare the derived volume/level/`pct_filled` against the paired historical record. Compute and store the **residual/error** per pair.
- **FR-GT-4 (Empirical rating-curve construction)** — Use the matched pairs to **build the reservoir's area↔storage↔level relationship directly from observed data**, regressing **extracted surface area** against the historical fields — **current reservoir level (m)**, **current live storage (BCM)**, and **`pct_filled`** — and anchoring the fit with **FRL** and **full live capacity at FRL** (area/storage/level at FRL define the curve's top bound). This yields per-reservoir **Area→Storage (BCM)** and **Area→Level (m)** functions that inherently absorb SAR-extraction bias and real basin behaviour. The DEM-derived hypsometric curve is **blended** with the empirical fit into a single per-reservoir rating curve (see [ADR-0004](../docs/adr/0004-blended-rating-curve-dem-empirical.md)): the empirical fit (ground-truth-anchored) owns the observed range; the DEM curve supplies independent geometry **above the observed maximum up to FRL** (the near-FRL release zone) and a cross-check in the overlap. The DEM only describes terrain above its acquisition-epoch waterline, so it contributes *shape* there while the empirical curve supplies the absolute offset. *Note:* a DEM captures terrain **above the water surface at its acquisition date**, so it is valid precisely for extrapolating *upward* toward FRL (banks above water) but cannot describe submerged bathymetry below that line — which is why the empirical fit owns the low/mid range. Persist the calibrated curve, versioned, with its valid (observed) range flagged.
- **FR-GT-5 (Extraction-method validation & selection)** — Run the harness in [ADR-0007](../docs/adr/0007-water-extraction-harness.md): cold-start unsupervised candidates (`Otsu-VH`, `K-means[VV,VH]`, `GMM[VV,VH]`); a U-Net added later, trained on weak labels (FR-GT-6). **Select the end-to-end pipeline** — each candidate co-fit with its own blended rating curve — by **derived fill-% MAE vs bulletins on a walk-forward / leave-one-season-out holdout**, broken out **by season/regime** (monsoon / winter-ice / wind-roughened) so robustness, not just mean error, governs promotion. Track all candidates and metrics in MLflow; keep the winner pluggable & versioned.
- **FR-GT-6 (Label generation for supervised segmentation)** — Retain validated masks/areas from high-confidence, low-residual pairs as **weak labels** to train/improve a supervised segmentation model over time.
- **FR-GT-7 (Acceptance gating)** — Expose the ground-truthing accuracy (e.g. validation MAE on `pct_filled`/volume) as a **gate**: estimation, forecasting, and release prediction are only marked production-ready once ground-truthing meets the agreed tolerance (see §9).

### 5.4 AI / ML Pipeline (FR-ML)

- **FR-ML-1 (Estimation)** — Provide a calibrated mapping from satellite-derived surface area to **volume** and **level**, refined against ground truth (correcting systematic bias in the raw hypsometric estimate).
- **FR-ML-2 (Forecasting)** — Produce **1–14 day** fill-level (and volume / `pct_filled`) forecasts per reservoir from the historical + derived storage time series **and the catchment-forcing features (precipitation, antecedent index, snow-cover area, SWE, degree-day melt, forecast precip from FR-DE-7…11)**, with prediction intervals. The model shall be inflow-aware so that upstream rainfall/snowmelt drives the forecast rather than storage extrapolation alone.
- **FR-ML-3 (Release prediction — primary)** — Derive a **probability/likelihood of a flood/emergency release** per reservoir over the forecast horizon, computed from the forecast fill-level/storage trajectory relative to FRL and reservoir-specific release thresholds, **net of routine operational drawdown implied by the seasonal rule curve** (see §8.3 release taxonomy), with prediction uncertainty. Output a discrete **release-risk level** (Low / Watch / Warning / Imminent), the **estimated lead time**, and **contributing factors**.
- **FR-ML-4** — Track all experiments, parameters, metrics, and artifacts in **MLflow**; register promoted models in the MLflow model registry with versioning.
- **FR-ML-5** — Run **automated inference** to refresh current estimates, forecasts, and release-risk whenever new data lands; persist predictions with timestamps and model version.
- **FR-ML-6** — Because bulletin ground truth ends in April 2026 (closed loop, [ADR-0005](../docs/adr/0005-closed-loop-no-live-ground-truth.md)), accuracy is established by a **one-time rigorous historical backtest** (walk-forward over ~11 years). In production, "validation" becomes **internal-consistency & drift monitoring** — SAR-derived state vs forecast residuals, extraction confidence trends, feature drift, and physically-implausible jumps — surfaced to admins. No live ground-truth comparison is possible.

### 5.5 Backend API (FR-API)

- **FR-API-1** — Expose typed REST/JSON endpoints (FastAPI) for: reservoir catalogue & metadata, latest status, historical time series, forecasts, **release-risk (probability, level, lead time)**, water-mask/GeoJSON layers, accuracy metrics, alerts, and pipeline/system health.
- **FR-API-2** — Serve geospatial layers (AOI polygons, water masks) as GeoJSON suitable for Leaflet rendering.
- **FR-API-3** — Enforce authentication and RBAC on protected and admin endpoints.
- **FR-API-4** — Provide auto-generated OpenAPI documentation.
- **FR-API-5** — Provide admin endpoints to trigger/monitor pipeline runs and manage reservoir configurations.

### 5.6 Frontend Dashboard (FR-UI)

- **FR-UI-1** — Present a **real-time Leaflet map** showing each reservoir, its AOI, current water extent overlay, and colour-coded fill-status markers.
- **FR-UI-2** — Provide an **analytics dashboard** with KPI cards (current fill %, volume in BCM, level vs FRL, surface area) and interactive trend charts (current year vs last year vs normal).
- **FR-UI-3** — Show **forecast** charts (1–14 day) with confidence/prediction intervals, and the **release-risk outlook** (risk level, release probability, and estimated lead time) prominently per reservoir, including a colour-coded risk indicator on the map markers.
- **FR-UI-4** — Show **estimate-vs-ground-truth** comparison and accuracy indicators for analyst trust.
- **FR-UI-5** — Support reservoir selection, date-range filtering, and report/data export (CSV/PDF) for authorised roles.
- **FR-UI-6** — Surface **early-warning alerts** as the central feature — when a reservoir crosses a release-risk threshold (Watch/Warning/Imminent) — plus secondary alerts (approaching FRL, rapid level rise, stale data) and an admin view of pipeline/system health. Alerts are timestamped, acknowledgeable, and retained as a history.
- **FR-UI-7** — Deliver a **modern, clean, elegant, professional, responsive** UI/UX (desktop and mobile browsers), with accessible (WCAG-aware) components and clear loading/empty/error states.

---

## 6. Data Requirements

### 6.1 Input data sources (all open / free)

- **Sentinel-1 SAR (GRD)** — via Google Earth Engine; primary source of water extent. Revisit ~6–12 days.
- **Digital Elevation Model (DEM)** — via GEE (e.g. SRTM/Copernicus DEM); basis for the hypsometric curve and catchment delineation.
- **Ground-truth bulletins** — historical reservoir time series already extracted by the companion `dataExtractor` project.
- **Precipitation** — CHIRPS / GPM IMERG / ERA5-Land (catchment rainfall, observed).
- **Snow & temperature** — MODIS snow-cover (NDSI), ERA5-Land / GLDAS SWE, snowmelt & 2 m temperature (snowmelt drivers).
- **Forecast forcing** — NOAA GFS (`NOAA/GFS0P25`): forecast precipitation + 2 m temperature across the 1–14 day horizon.
- **Catchment / hydrography** — HydroSHEDS **HydroBASINS** + MERIT Hydro for delineating upstream contributing areas.

All of the above are accessible through **Google Earth Engine** via `geemap`/`xee` — see the catalogue in §6.6.

### 6.2 Ground-truth schema (source columns)

`SR. NO.`, `RESERVOIR NAME`, `FRL (M)`, `CURRENT RESERVOIR LEVEL (M)`, `LIVE CAPACITY AT FRL (BCM)`, `CURRENT LIVE STORAGE (BCM)`, `DATE`, `STORAGE AS % OF LIVE CAPACITY (current / last year / normal)`, `BENEFITS - IRR-CCA`, `BENEFITS - HYDEL IN MW`, `SOURCE_PDF`, `pct_filled`.

### 6.3 Core stored entities (logical model)

- **Reservoir** — id, name, basin, FRL, live capacity (BCM), AOI polygon (PostGIS geometry), **catchment polygon** (PostGIS geometry), rating-curve config, **release thresholds** (level/fill-% at which Watch/Warning/Imminent risk applies), and **seasonal operating rule curve** (target levels by date) used to distinguish flood/emergency spill from routine operational release.
- **CatchmentForcing** — reservoir_id, date, catchment_precip, antecedent_precip_index, snow_cover_area, swe, degree_day_melt, forecast_precip, source/dataset versions, freshness flags.
- **Observation (satellite-derived)** — reservoir_id, acquisition_date, surface_area, derived_volume, derived_level, water_mask_ref, scene metadata, provenance.
- **GroundTruth** — reservoir_id, date, level, live_storage_bcm, pct_filled, source_pdf.
- **GroundTruthMatch** — reservoir_id, gt_date, scene_id, time_gap_days, extracted_area, area_confidence, extraction_method/version, derived_volume, derived_level, residual_vs_ground_truth.
- **RatingCurve** — reservoir_id, version, fit type (empirical / DEM-prior / blended), curve points/params (**area↔storage(BCM)↔level(m)**), FRL/full-capacity anchors, **observed (valid) range** vs extrapolated range, fit metrics, created_at.
- **AnalyticalBaseTable (ABT / feature store)** — the canonical joined table, one row per `(reservoir, date)`, uniting **all** variables time-aligned via point-in-time joins: ground truth (level, live_storage_bcm, pct_filled, FRL, capacity), satellite-derived (surface_area, area_confidence, derived_volume/level, extraction_method), catchment forcing (precip, antecedent index, snow_cover_area, swe, degree_day_melt, forecast_precip), engineered features, source/freshness flags, and residuals. This is the single dataset the rating curve, forecaster, and release model train and infer on (see §6.7).
- **Prediction** — reservoir_id, run_timestamp, horizon_date, predicted value(s), interval, model_version.
- **ReleaseRisk** — reservoir_id, run_timestamp, release_probability, risk_level (Low/Watch/Warning/Imminent), estimated_lead_time_days, contributing factors, model_version.
- **Alert** — reservoir_id, type (flood-release / approaching-FRL / rapid-rise / data-quality), severity, triggered_at, message, contributing_factors, release_risk_ref, acknowledged_by/at, resolved_at. (In-app + audit history; external push deferred — see §2 Non-Goals.)

### 6.4 Storage model

- **PostgreSQL + PostGIS**: geometries (AOI, water masks) and all metric/time-series + application data.
- **MLflow artifact store**: trained models, parameters, metrics, evaluation artifacts.
- Object/file storage (or DB references) for raster/mask exports as needed.

### 6.5 Retention & provenance

- All derived estimates retain full provenance (scene IDs, params, AOI/model versions).
- Historical observations and predictions are retained for trend analysis and model retraining.

### 6.6 Google Earth Engine data catalogue (via `geemap` + `xee`)

Every dataset the platform consumes is **open and hosted in the GEE Data Catalog**, so it can be accessed with `geemap` (server-side EE compute) and `xee` (open as `xarray` for catchment time-series extraction into ML features). Exact asset IDs, band selections, and thresholds are confirmed during implementation; bands listed are the primary ones used.

| Purpose | Dataset | GEE asset ID | Key bands / vars | Resolution · cadence |
| --- | --- | --- | --- | --- |
| **Water extent (SAR)** | Sentinel-1 GRD | `COPERNICUS/S1_GRD` | `VV`, `VH` backscatter | 10 m · ~6–12 d revisit |
| **Elevation (volume + catchment)** | Copernicus DEM GLO-30 | `COPERNICUS/DEM/GLO30` | `DEM` | 30 m · static |
| Elevation (alt.) | SRTM | `USGS/SRTMGL1_003` | `elevation` | 30 m · static |
| **Catchment basins** | HydroSHEDS HydroBASINS | `WWF/HydroSHEDS/v1/Basins/hybas_1…hybas_12` | basin polygons (Pfafstetter, L1–L12) | static |
| Hydrography (routing) | MERIT Hydro | `MERIT/Hydro/v1_0_1` | `dir`, `upa` (flow dir, accumulation), rivers | ~90 m · static |
| **Precipitation (observed)** | CHIRPS Daily | `UCSB-CHG/CHIRPS/DAILY` | `precipitation` | ~5.5 km · daily |
| Precipitation (observed) | GPM IMERG | `NASA/GPM_L3/IMERG_V07` | `precipitation` | ~11 km · 30-min |
| **Precip + temp + snow (reanalysis)** | ERA5-Land Daily | `ECMWF/ERA5_LAND/DAILY_AGGR` | `total_precipitation_sum`, `temperature_2m`, `snow_depth_water_equivalent` (SWE), `snowmelt_sum` | ~11 km · daily |
| Snow & melt (land-surface) | GLDAS-2.1 Noah | `NASA/GLDAS/V021/NOAH/G025/T3H` | `SWE_inst`, `Qsm_acc` (snowmelt), `Tair_f_inst` | ~28 km · 3-hourly |
| **Snow-cover area** | MODIS Terra Snow Cover | `MODIS/061/MOD10A1` | `NDSI_Snow_Cover` | 500 m · daily |
| Climate (context) | TerraClimate | `IDAHO_EPSCOR/TERRACLIMATE` | `pr`, `swe`, `tmmx`, `tmmn` | ~4 km · monthly |
| **Forecast forcing** | NOAA GFS 0.25° | `NOAA/GFS0P25` | `total_precipitation_surface`, `temperature_2m_above_ground` | ~28 km · 16-day forecast, 4×/day |

Notes:

- **Catchment extraction:** select the HydroBASINS polygon(s) draining to the dam (finest level for small basins); MERIT Hydro `upa` validates the delineated area against known basin size.
- **Snowmelt strategy:** *observed* melt/SWE from ERA5-Land (`snowmelt_sum`, `snow_depth_water_equivalent`) and/or GLDAS (`Qsm_acc`, `SWE_inst`); *forward* melt **derived** from GFS forecast `temperature_2m_above_ground` via the degree-day index (no native snowmelt-forecast product exists).
- **Access pattern:** `xee` opens each collection clipped to the AOI/catchment as an `xarray.Dataset`; the pipeline reduces to catchment-mean (and snow-cover fraction) time series, time-aligned to the storage record, and writes the `CatchmentForcing` table.

### 6.7 Unified Analytical Base Table (feature store) — required

All downstream modelling depends on a **single, time-aligned table that joins every variable** so the relationships between them can actually be learned. This is the keystone dataset. Its concrete, **frozen column-level schema** (and the `Observation` schema that feeds it) is the inter-pipeline contract in [`docs/contracts/observation-and-abt.md`](../docs/contracts/observation-and-abt.md) — see [ADR-0003](../docs/adr/0003-frozen-pipeline-contracts.md). The requirements below define *what* it must contain; the contract defines the *exact columns, types, units, grain (daily IST), and null rules*.

- **FR-ABT-1 (Canonical join)** — Build one **Analytical Base Table** keyed on `(reservoir_id, date)` that joins ground-truth bulletin values, satellite-derived surface area + estimates, and catchment-forcing features (precip, antecedent index, snow-cover area, SWE, degree-day melt, forecast forcing) into a single row per reservoir per date.
- **FR-ABT-2 (Temporal alignment policy)** — Define and apply an explicit alignment policy: nearest-match within tolerance for irregular series (imagery ↔ bulletin, per §5.3), resampling/aggregation for higher-cadence series (sub-daily forcing → daily), and **timezone-correct** handling (bulletins are IST, satellite/forcing are UTC).
- **FR-ABT-3 (Point-in-time correctness — no leakage)** — Each row contains only information **knowable at that timestamp** (e.g. the GFS forecast *issued* then, not a later reanalysis), so training and serving see consistent inputs and the future never leaks into the past.
- **FR-ABT-4 (Versioned & reproducible)** — The ABT is versioned and snapshot-able so any model run is reproducible against the exact data it saw (recorded in MLflow).
- **FR-ABT-5 (Quality & coverage flags)** — Carry per-row provenance, freshness, confidence, and an **observed-vs-extrapolated** flag; mark rows with missing/low-quality inputs so models can weight or exclude them.

---

## 7. Non-Functional Requirements

### 7.1 Accuracy (acceptance-critical)

- **NFR-ACC-1 (ground-truthing — foundational)** — On the **nearest-imagery matched set** (§5.3), the ML-extracted-area-derived **volume/level** shall agree with the paired historical ground-truth within a defined tolerance (target: **fill-% MAE ≤ 5–10%**; final threshold confirmed during calibration). The temporal match gap shall stay within the configured tolerance, and this metric gates downstream production-readiness.
- **NFR-ACC-2** — **1–14 day forecasts** shall meet a defined skill threshold (e.g. beat a persistence/naïve baseline; target horizon-1 fill-% MAE within agreed bound).
- **NFR-ACC-3 (release prediction — primary)** — Release-risk is a transparent function of the forecast trajectory vs FRL/threshold bands (see [ADR-0001](../docs/adr/0001-release-risk-is-a-layer-not-a-validated-classifier.md)). It shall be optimised for **high recall on actual flood/emergency release events** and provide a **minimum useful lead time** (target ≥ 2–3 days). Recall/precision/lead-time/calibration are reported from the **~11-year historical backtest** on held-out near-FRL episodes, but are **not live acceptance gates** — the closed loop ([ADR-0005](../docs/adr/0005-closed-loop-no-live-ground-truth.md)) means no production ground truth exists to re-validate them, and no future release is observed live. Metrics use **precision-recall** (not ROC) given event rarity.
- **NFR-ACC-4** — Accuracy metrics (estimation, forecast skill, release recall/precision, lead time, calibration) are established by the **historical backtest** and shown in the dashboard as the system's stated accuracy. Live, post-deployment metrics are limited to **internal-consistency and drift** indicators, since no incoming ground truth exists (closed loop, [ADR-0005](../docs/adr/0005-closed-loop-no-live-ground-truth.md)).

### 7.2 Timeliness & data-availability SLA

- **NFR-TIME-1** — New Sentinel-1 acquisitions are detected and processed within **24 hours** of availability in GEE.
- **NFR-TIME-2** — "Real-time" is explicitly bounded by the **satellite revisit cadence (~6–12 days)**; the UI clearly displays last-acquisition date and data freshness.
- **NFR-TIME-3** — Dashboard API responses for cached/served data return in **< 1 s** (p95) under normal load.

### 7.3 Scalability

- **NFR-SCALE-1** — Onboarding additional reservoirs is config-driven and linear in cost; the pipeline processes the full fleet within its scheduling window.
- **NFR-SCALE-2** — Services are independently scalable (stateless API; pipeline workers scalable horizontally).

### 7.4 Reliability & observability

- **NFR-REL-1** — Pipelines are idempotent and automatically retried with backoff on transient failures; failures alert administrators.
- **NFR-REL-2** — Structured logging, run status, and health endpoints for every service; pipeline run history is queryable.
- **NFR-REL-3** — Target service availability **≥ 99%** for the serving layer (API + dashboard).
- **NFR-REL-4** — Automated database backups with defined recovery objectives.
- **NFR-REL-5 (audit trail)** — Retain an immutable record of **what was predicted/alerted, when, on which data and model version** — for post-event accountability and review of any flood-release warning.
- **NFR-REL-6 (graceful degradation)** — When no fresh imagery is available, the system must not go silent: it continues to serve forecast-based risk from the last-known state and clearly flags staleness, rather than failing or hiding.

### 7.5 Security

- **NFR-SEC-1** — Authentication + **RBAC** for protected/admin functionality.
- **NFR-SEC-2** — Secrets (GEE credentials, DB, tokens) managed via environment/secret stores — never committed.
- **NFR-SEC-3** — HTTPS/TLS in transit; least-privilege DB access; input validation on all endpoints.

### 7.6 Maintainability & reproducibility

- **NFR-MNT-1** — Reproducible Python environments via **`uv`** lockfiles; reproducible deploys via **Docker**.
- **NFR-MNT-2** — All ML runs reproducible through MLflow-tracked params/data/versions.
- **NFR-MNT-3** — Clear module boundaries between the three pipelines and the serving layer, communicating via well-defined data/API contracts.

### 7.7 Usability

- **NFR-UX-1** — Professional, consistent visual design system; responsive layout; accessible components; informative loading/empty/error states.

### 7.8 Testing & data quality

- **NFR-TEST-1** — **Automated data-validation checks** on every pipeline run (e.g. Great Expectations / `pandera`): schema, ranges, nulls, temporal continuity, and cross-field consistency; failing data is quarantined, not silently propagated.
- **NFR-TEST-2** — **Unit + integration tests** for pipeline stages, the rating-curve/estimation logic, the API, and the ABT joins; **CI** runs them on every change.
- **NFR-TEST-3** — At least one **end-to-end backtest against a known historical near-FRL / release episode** is part of the acceptance suite.

---

## 8. ML / Analytics Specification

### 8.1 Water extraction & estimation (image → area → volume → level)

- **Water extraction (ML-based):** segment water from SAR using unsupervised clustering (K-means / Gaussian-mixture / Otsu on backscatter) and/or a trained segmentation model (Random-Forest pixel classifier / U-Net). Method is pluggable, versioned, and selected by the ground-truthing workflow (§5.3).
- **Empirical conversion (primary):** the per-reservoir **Area→Storage (BCM)** and **Area→Level (m)** rating curve fitted in ground-truthing (FR-GT-4) directly from matched `(extracted_area, current_level, current_live_storage_BCM, pct_filled)` pairs, anchored by FRL and full live capacity. This maps newly extracted area straight to storage, level, and fill-%.
- **DEM prior / backstop:** the DEM-derived hypsometric curve provides a physics prior and a sanity check; it extrapolates only above the observed fill maximum (small, since the pilot history reaches near-FRL) and supplies cold-start curves for reservoirs without local history yet.
- **Output:** calibrated current volume (BCM), level (m), and fill-% per reservoir per acquisition, with an indicator when the value relies on extrapolation beyond the observed range.

### 8.2 Forecasting (1–14 day)

- **Inputs:** the unified Analytical Base Table (§6.7) — historical + derived storage series, engineered features (recent rate-of-change, seasonality), and **catchment-forcing features** (precip + antecedent index, snow-cover area, SWE, degree-day melt, forecast precip). These make the forecast **inflow-aware** (causal) rather than pure storage extrapolation, extending warning lead time. All forcing sources are open datasets.
- **Train/serve consistency (critical):** at inference the model is fed **forecast** precip/temperature (GFS), but naïvely training on *observed* precip creates train/serve skew. Training shall use **archived GFS forecasts (reforecasts)** for the forecast-horizon features — or explicitly model the observed→forecast gap — so the model learns on the same noisy inputs it will serve on.
- **Approach (decided — [ADR-0006](../docs/adr/0006-forecaster-pooled-delta-fill-conformal.md)):** a **single pooled model across the three reservoirs on `pct_filled`** (reservoir-specific features for differentiation), predicting **Δ`pct_filled` over horizon h, inflow-aware, direct multi-horizon (1–14)** with light mass-balance structure (inflow netted against the Normal-Storage recession). Start with a **regularized gradient-boosted regressor**, trained on **SAR-derived state** ([ADR-0005](../docs/adr/0005-closed-loop-no-live-ground-truth.md)) for train/serve consistency; add capacity only when walk-forward skill earns it. **Conformal prediction intervals.** Benchmarked against **persistence and Normal-Storage climatology**. Horizon resolution is effectively ~weekly (target cadence), interpolated to daily with intervals widening between observation dates.
- **Output:** per-reservoir 1–14 day forecasts of level / volume / fill-% with uncertainty.

### 8.3 Release prediction (primary)

- **Release taxonomy (critical):** the system must distinguish a **flood / emergency spillway release** (the disaster signal this product warns about) from a **routine operational release** for irrigation or hydropower, which occurs year-round *below* FRL per the **operating rule curve**. Conflating the two causes both missed flood warnings and alarm fatigue. Release-risk alerts target the flood/emergency class; operational drawdown is modelled as expected behaviour (and as an outflow term, below).
- **Definition of a release event:** a flood/emergency discharge inferred when the reservoir is at/near FRL (or projected to exceed safe storage) with a sharp storage drop after peak fill, **net of the rule-curve operational drawdown**. Where explicit release/gate logs are unavailable, episodes are **derived from the ground-truth time series** (level near FRL → drawdown beyond the seasonal rule curve) to build training/validation labels; labels are treated as weak/noisy. The "seasonal rule curve" here is the bulletin **Normal Storage** column used as a proxy — official BBMB rule curves are not published (see [ADR-0002](../docs/adr/0002-normal-storage-as-rule-curve-proxy.md)).
- **Physical framing (mass balance):** reason about storage as `Δstorage = inflow − (release + evaporation + seepage + abstraction)`. A flood release becomes likely when forecast inflow would push storage above safe capacity faster than operational outflow can absorb — a more explainable basis than storage extrapolation alone. Evaporation is non-trivial in summer and should be included as an outflow term where estimable.
- **Approach:** translate the forecast fill-level/storage trajectory and its uncertainty into a **release probability** for the flood class; map to discrete **risk levels** (Low/Watch/Warning/Imminent) and compute **estimated lead time**.
- **Optimisation target:** maximise recall on actual **flood/emergency** releases at the required lead time, keep probabilities **calibrated** (e.g. isotonic/Platt or conformal), and keep false alarms tolerable (see NFR-ACC-3).
- **Explainability:** every release-risk output exposes its **contributing factors** (e.g. current fill vs FRL, forecast precip, snowmelt, rate-of-rise) so authorities can see *why* — a requirement for accountable disaster decisions.
- **Output:** per-reservoir release probability, risk level, lead time, and contributing factors — refreshed on every new acquisition.

### 8.4 Validation & ground-truthing methodology

- **Foundational ground-truthing (§5.3):** pair each historical record with its nearest Sentinel-1 acquisition (within the time tolerance), extract area via the ML method, convert through the hypsometric/rating curve, and validate derived volume/level/`pct_filled` against the historical record. Use these matched pairs to fit and validate the per-reservoir rating curve and to select the extraction method.
- Time-based train/validation split (no leakage across the forecast horizon).
- Metrics: MAE / RMSE / MAPE on fill-%, volume, and level; extraction-derived-volume error vs ground truth; forecast skill vs baseline.
- Validation is a **historical backtest** over the ~11-year record (no incoming bulletins post-April-2026); production monitoring is internal-consistency/drift only (closed loop, [ADR-0005](../docs/adr/0005-closed-loop-no-live-ground-truth.md)).
- All experiments, metrics, and selected models tracked and versioned in **MLflow**.

### 8.5 Modelling under data scarcity (governing constraint)

The available history is **moderate** — roughly weekly bulletins, three reservoirs, **~11 annual cycles** (2015-07 → 2026-04, ~583 records). It reaches near-FRL across many monsoon peaks, so the fill range is well covered, and multiple independent seasons make **walk-forward / leave-one-season-out CV feasible**. What remains genuinely limited is **spatial diversity** (only three reservoirs) and the number of true **flood-release events** (rare relative to total observations). The governing constraint is now less about data *volume* and more about the **closed loop**: bulletin ground truth **ends in April 2026** and never resumes (see [ADR-0005](../docs/adr/0005-closed-loop-no-live-ground-truth.md)) — production runs on SAR + DEM + forcing alone, so the estimation bridge (rating curve) must carry the system unaided and live accuracy cannot be re-validated against new bulletins. This regime governs every modelling choice:

- **Prefer simple, physics-informed models** (the empirical rating curve, mass-balance framing, degree-day melt) over high-capacity deep nets that would overfit; add capacity only when validation skill justifies it.
- **Pool across reservoirs** (shared/transfer models with per-reservoir adjustments) to multiply effective sample size; support **cold-start** for new reservoirs via the DEM prior + pooled model until local history accrues.
- **Validate honestly:** leave-one-season-out / walk-forward (expanding-window) cross-validation; report uncertainty with **conformal prediction** or ensembles rather than over-trusting point estimates.
- **Handle rarity & imbalance:** class weighting / threshold tuning for release events; treat derived release labels as noisy.
- **Expect to improve with data:** each new monsoon season — especially near-FRL observations — materially strengthens the curve and the release model; retraining is scheduled as data accrues.

---

## 9. Acceptance Criteria & KPIs

The platform is accepted for production when:

- **AC-1** — All three pipelines run end-to-end automatically on schedule, with no manual steps, for the full pilot fleet.
- **AC-2 (foundational gate)** — Ground-truthing succeeds: each historical record is matched to its nearest in-tolerance Sentinel-1 acquisition, ML-extracted area is converted via the calibrated rating curve, and derived volume/level agrees with ground truth within NFR-ACC-1. The selected extraction method and per-reservoir rating curve are validated and versioned.
- **AC-3** — Estimation accuracy meets NFR-ACC-1 on the held-out validation set.
- **AC-4** — 1–14 day forecasts meet NFR-ACC-2 (beat the naïve baseline) with published uncertainty.
- **AC-5 (primary)** — Release-risk prediction meets NFR-ACC-3: on a **held-out set of historical near-FRL episodes across the ~11-year record**, the risk indicator achieves the agreed recall at the minimum lead time with calibrated probabilities, **plus illustrative case studies** (see [ADR-0001](../docs/adr/0001-release-risk-is-a-layer-not-a-validated-classifier.md)), producing a clear risk level and contributing factors per reservoir. These are **backtest** acceptance numbers; live recall cannot be measured post-deployment (closed loop, [ADR-0005](../docs/adr/0005-closed-loop-no-live-ground-truth.md)).
- **AC-6** — The dashboard renders the real-time Leaflet map, release-risk indicators, early-warning alerts, KPI cards, trend/forecast charts, and accuracy comparison, meeting the professional UI/UX bar.
- **AC-7** — New Sentinel-1 data is reflected within the NFR-TIME SLA, with data-freshness clearly shown, and release-risk is refreshed on every new acquisition.
- **AC-8** — The full stack runs reproducibly via Docker Compose from a clean checkout.
- **AC-9** — RBAC, logging, health monitoring, and automated backups are operational.
- **AC-10** — The unified Analytical Base Table (§6.7) is built, point-in-time correct (no leakage), versioned, and is the dataset all models train/infer on.
- **AC-11** — On a release-risk threshold crossing, an **in-app alert** is generated, persisted with a timestamped, acknowledgeable **history**, and recorded in the audit trail (NFR-REL-5). *(External push delivery is deferred to v2 — see §2.)*
- **AC-12** — Automated data-validation and the regression backtest (§7.8) pass in CI.

**Operational KPIs:** **mean warning lead time (headline)**, plus release-event recall and false-alarm rate (monitored/accruing — not v1 gates, per [ADR-0001](../docs/adr/0001-release-risk-is-a-layer-not-a-validated-classifier.md)); **forecast skill vs baseline** and estimation MAE (the validated v1 accuracy gates); pipeline success rate; data freshness lag; API p95 latency; service uptime.

---

## 10. Assumptions, Constraints & Risks

### Assumptions

- Sentinel-1 and DEM data remain accessible via Google Earth Engine under the project's credentials.
- Historical bulletin ground truth is available and reasonably accurate for calibration/validation.
- Each reservoir has (or can be assigned) a stable AOI and an obtainable hypsometric curve.
- The historical records provide FRL, current level, full live capacity, and current live storage (BCM) per date — sufficient to build the empirical area↔storage↔level relationship across nearly the full fill range (the pilot history reaches ~90–100% on all three reservoirs); only the thin band above each reservoir's observed maximum needs DEM-prior extrapolation.
- A seasonal operating rule curve proxy is available: the bulletin **Normal Storage** column serves this role in v1, since official BBMB rule curves are not published (see [ADR-0002](../docs/adr/0002-normal-storage-as-rule-curve-proxy.md)). Replacing it with official curves is a v2 upgrade.
- Reservoir live capacity is treated as time-varying (sedimentation); rating curves and capacity carry a validity date and are periodically re-fit.

### Constraints

- Update frequency is bounded by Sentinel-1 revisit (~6–12 days) — not continuous real-time.
- SAR water detection accuracy is affected by wind-roughened water, terrain shadow, and frozen surfaces.
- Hybrid compute requires reliable connectivity between GEE processing and self-hosted services.
- **Open-data / open-source only** — no paid datasets or paid software (see §4.4); GEE is used under its free non-commercial tier with a documented swappable-backend migration path.
- Hydromet datasets vary in **resolution and latency** (e.g. ERA5-Land ~9 km with a few-days lag; IMERG/CHIRPS daily) — features inherit those limits and must carry freshness flags.

### Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| SAR misclassification (rough water / terrain) | Robust thresholding + ground-truth calibration + anomaly gates |
| Sparse/irregular ground truth | Nearest-date fusion + uncertainty reporting; flag low-confidence estimates |
| GEE quota / availability limits | Backoff/retry, caching, scheduled batching within quota |
| Hypsometric-curve error | Empirical area↔storage↔level fit from matched pairs corrects systematic bias against ground truth |
| Empirical curve extrapolates only above the observed maximum (the pilot history already reaches ~90–100% fill, so this gap is now small) | Flag the few extrapolated estimates above the observed max; fall back to DEM hypsometric prior there; widen uncertainty; the residual gap closes further with each new monsoon peak |
| Model drift over seasons | Continuous validation + MLflow-tracked retraining |
| Sparse / unlabelled release events for training | Derive release labels from ground-truth level/drawdown patterns; favour recall; report confidence and treat early versions as decision-support, not sole authority |
| Revisit gap (~6–12 days) may miss a fast release | Forecast bridges the gap; clearly show data-freshness and forecast-based risk between acquisitions; flag stale data |
| Coarse-resolution / lagged hydromet data over steep Himalayan catchments | Treat forcing as features (not exact inflow); aggregate over catchment; use multiple precip products; carry freshness/uncertainty flags |
| Catchment delineation error from DEM | Validate delineated area against known basin size; allow manual override of the catchment polygon |
| Snow-cover optical gaps under cloud | Prefer ERA5-Land SWE/temperature (cloud-free reanalysis) for melt; use MODIS snow-cover as a complementary signal |
| GFS forecast precip is uncertain over steep terrain and degrades with lead time | Use forecast as a feature with widening prediction intervals by horizon; lean on the snowpack (slower, more predictable) signal; refresh on each GFS update |
| Conflating routine operational releases with flood/emergency spills | Separate classes via the seasonal rule curve; alert only on the flood class; model operational drawdown as expected outflow |
| Train/serve skew (observed precip in training, forecast precip at inference) | Train on archived GFS reforecasts (or model the gap) so inputs match at serve time |
| Overfitting in the small-data regime | Simple/physics-informed + pooled models; leave-one-season-out CV; conformal intervals; capacity added only when justified |
| Sedimentation ages the rating curve and lowers true live capacity over years | Treat curves as dated/versioned; periodically re-fit from fresh matched pairs; flag when capacity assumptions drift |
| Upstream cascade dams / GLOF / cloudburst extremes alter inflow abruptly | Acknowledge as edge cases; include upstream signals where available; rely on radar's all-weather observation + rapid re-forecast; flag anomalous rises |

---

## 11. Glossary

| Term | Definition |
| --- | --- |
| **SAR** | Synthetic Aperture Radar — active radar imaging (Sentinel-1); cloud- and daylight-independent |
| **GRD** | Ground Range Detected — a Sentinel-1 SAR product level |
| **DEM** | Digital Elevation Model — terrain elevation grid used to derive volume from area |
| **Hypsometric curve** | The area–elevation–volume relationship of a reservoir basin |
| **Rating curve** | The (calibrated) mapping between surface area, volume, and level for a specific reservoir |
| **Image segmentation** | Partitioning an image into regions (here, water vs non-water) — via clustering or a trained model (e.g. U-Net) |
| **Clustering** | Unsupervised grouping of pixels by backscatter (e.g. K-means / Otsu / GMM) to separate water from land without labels |
| **Temporal nearest-match** | Pairing a ground-truth record with the closest-in-time satellite acquisition, within a tolerance |
| **Weak labels** | Imperfect training labels (validated masks from low-residual matches) used to train supervised segmentation |
| **Catchment** | The upstream contributing area whose precipitation/snowmelt drains into a reservoir |
| **Snowmelt** | Conversion of catchment snowpack to runoff; the dominant spring/summer inflow source for these Himalayan reservoirs |
| **SWE** | Snow Water Equivalent — the water content held in the snowpack |
| **Snow-cover area (SCA)** | Fraction/extent of the catchment covered by snow (e.g. MODIS NDSI) |
| **Degree-day / temperature-index melt** | Simple snowmelt estimate proportional to temperature above a threshold |
| **Antecedent precipitation index** | A decayed sum of recent rainfall capturing how wet the catchment already is |
| **CHIRPS / IMERG / ERA5-Land / GLDAS** | Open precipitation/climate/land-surface datasets used for catchment forcing |
| **HydroBASINS** | HydroSHEDS nested sub-basin polygons (Pfafstetter levels 1–12); source of reservoir catchments, hosted in GEE |
| **GFS** | NOAA Global Forecast System — open 16-day weather forecast (precip + temperature), hosted in GEE |
| **`geemap` / `xee`** | Python libraries for Google Earth Engine: `geemap` (server-side EE + mapping), `xee` (open EE collections as `xarray`) |
| **FRL** | Full Reservoir Level — maximum normal operating level (m); the reference for release risk |
| **Release / release event** | Controlled or emergency discharge of water from the reservoir (spillway/sluice), the downstream-flood trigger this system warns against |
| **Release-risk level** | Discrete warning tier derived from release probability: Low / Watch / Warning / Imminent |
| **Lead time** | Days of advance warning between a release-risk alert and the predicted release |
| **Rule curve** | A reservoir's seasonal target-level schedule guiding routine operation; used to separate operational releases from flood spills |
| **Analytical Base Table (ABT)** | The single joined, time-aligned table (one row per reservoir·date) of all variables that models train/infer on |
| **Point-in-time join** | An as-of join including only data knowable at each timestamp, preventing future-information leakage |
| **Mass / water balance** | Δstorage = inflow − (release + evaporation + seepage + abstraction) |
| **Reforecast** | An archived historical model forecast (e.g. past GFS runs) used so training inputs match what is seen at serving |
| **Conformal prediction** | A method producing calibrated prediction intervals with finite-sample guarantees, suited to small data |
| **BCM** | Billion Cubic Metres — unit of stored water volume |
| **Live storage** | Usable stored water between minimum draw-down and FRL |
| **`pct_filled`** | Storage as a percentage of live capacity at FRL |
| **AOI** | Area of Interest — the geographic polygon delineating a reservoir |
| **Ground truth** | Reference measurements (official bulletin gauge readings) used to validate estimates |
| **Medallion (bronze/silver/gold)** | Layered data-refinement pattern: raw → cleaned → analytics-ready |
| **GEE** | Google Earth Engine — cloud platform for satellite data access/processing |
| **RBAC** | Role-Based Access Control |

---

*End of specification.*
