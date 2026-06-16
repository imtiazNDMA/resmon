# Plan 02 — Database & Data-Model Implementation

**Owner:** Database engineering (PostgreSQL/PostGIS)
**Status:** Draft for review
**Date:** 2026-06-16
**Stack:** Monorepo + `uv`; SQLAlchemy 2.x models in `core/`, Alembic migrations in `db/`, Pydantic v2 schemas mirroring the models; PostgreSQL 16 + PostGIS 3.4.

This plan is the **canonical data-contract owner** for the §6.3 stored entities and the §6.7 Analytical Base Table. Other teams (Remote-Sensing/DE, ML, API) build against the table and column names frozen here. Where the spec already froze a schema — `docs/contracts/observation-and-abt.md` (`contract_version: 2`) — this plan mirrors it **byte-for-byte** and treats it as authoritative; any divergence is a bug in this plan.

---

## 1. Scope & owned requirements

I own the full logical→physical schema and migrations for every stored entity, plus point-in-time correctness of the ABT, retention/partitioning, data-quality constraints, and backup alignment.

| Area | Requirement IDs |
| --- | --- |
| Core entities (Reservoir, Observation, GroundTruth, GroundTruthMatch, RatingCurve, CatchmentForcing, Prediction, ReleaseRisk, Alert, ABT, ForecastForcing) | §6.3, §6.7 |
| AOI + catchment PostGIS geometries, SRID, spatial indexes | FR-RS-1, FR-DE-7, FR-API-2 |
| Rating-curve config (blended), observed-vs-extrapolated range, versioning, sedimentation validity dates | FR-GT-4, ADR-0004, §10 (time-varying capacity) |
| Release thresholds + seasonal rule-curve proxy (Normal Storage) | FR-ML-3, §8.3, ADR-0002 |
| Time-series storage, partitioning & retention | §6.5, NFR-SCALE-1 |
| Data-quality gates & check constraints | FR-DE-4, NFR-TEST-1 |
| ABT point-in-time correctness, versioning, quality/freshness flags | FR-ABT-1…5, AC-10 |
| Provenance / audit trail (predictions, alerts, model versions) | FR-RS-6, NFR-REL-5 |
| Idempotent upserts (natural keys) | FR-DE-6, §4.3 |
| RBAC users/roles | §3, §7.5, NFR-SEC-1 |
| Backups & recovery objectives | NFR-REL-4 |
| Frozen inter-pipeline contracts | ADR-0003, contract v2 |

**Primary acceptance targets:** **AC-2** (ground-truthing: GroundTruthMatch + RatingCurve persisted, versioned, with residuals) and **AC-10** (ABT built, point-in-time correct, versioned, the sole modelling dataset).

---

## 2. Upstream dependencies

| Dependency | What I need from it | Status |
| --- | --- | --- |
| Frozen contract `observation-and-abt.md` v2 | Exact `Observation`, `AnalyticalBaseTable`, `ForecastForcing` columns/types/units/null rules | **Available, authoritative** — mirrored here |
| ADR-0002 | Normal Storage is the rule-curve proxy → `rule_curve` stored as `normal_storage_pct` series, not official curve | Available |
| ADR-0003 | Contract-version discipline; stub `Observation` rows (`extraction_method='stub'`) | Available |
| ADR-0004 | Blended rating curve: store both valid ranges + DEM-epoch waterline | Available |
| ADR-0005 | Closed loop → bulletins are a bootstrap corpus; production writes only SAR/forcing/derived. No live GT ingestion path after cutover | Available |
| §6.2 ground-truth source columns | `GroundTruth` raw column mapping (dataExtractor output) | Available |
| §6.6 GEE catalogue | Dataset/asset IDs recorded in `source_versions` provenance jsonb | Available |
| AOI provenance (FR-RS-1) | AOI derived from JRC GSW → versioned GeoJSON. I store geometry + version; RS pipeline produces it | RS pipeline owns content |

No blocking upstream gaps. The contract being frozen lets me proceed immediately.

---

## 3. Downstream consumers

| Consumer | Reads | Writes |
| --- | --- | --- |
| **Remote-Sensing / DE pipeline** | `reservoir` (AOI geom, aoi_version, orbit/pass config) | `observation`, `catchment_forcing`, `forecast_forcing`, `ground_truth`, `ground_truth_match`, `rating_curve`, `analytical_base_table`, `pipeline_run` |
| **ML pipeline** | `analytical_base_table` + `forecast_forcing` (training/inference), `rating_curve`, `reservoir` thresholds | `prediction`, `release_risk`, `model_version` registry rows (mirror of MLflow) |
| **API (FastAPI)** | everything (read-mostly); RBAC tables | `alert` ack/resolve, `user`/session writes, pipeline trigger rows |
| **Frontend** | via API only | — |

**Contract surface exposed:** the canonical table/column names in §5–§6 below, plus SQLAlchemy models at `core/models/` and Pydantic v2 schemas at `core/schemas/` (§11).

---

## 4. Cross-cutting design decisions

### 4.1 SRID choice
- **Storage SRID: 4326 (WGS84)** for all geometry columns. Rationale: source data (Sentinel-1 footprints, JRC GSW, HydroBASINS, MERIT, DEM) and the API/Leaflet output (FR-API-2, GeoJSON) are all lon/lat; storing in 4326 avoids reprojection on every read.
- **Geometry type:** `geometry(MultiPolygon, 4326)` for AOI, catchment, and water-mask vector footprints (multipolygon, not polygon, because water extent and catchments can be multi-part).
- **True-area computation is NOT done in SQL.** Per FR-RS-3 surface area is computed in GEE with `ee.Image.pixelArea()` / an equal-area projection and **delivered as a numeric `surface_area` (km²)** into `observation`. The DB never derives area from 4326 polygons (that would be wrong at these latitudes). For any incidental server-side area/length sanity check we use `ST_Area(geog::geography)`.
- **`geography` vs `geometry`:** keep `geometry(…,4326)` (not `geography`) for index richness and Leaflet compatibility; cast to `::geography` only for the rare metric check.

### 4.2 Identity & keys
- **`reservoir_id` is `text`** (slug, e.g. `gobind_sagar`, `pong`, `thein`) — matches the frozen contract (`text`, not int). Human-readable, config-driven onboarding (NFR-SCALE-1), stable across reloads.
- All time-series tables use **composite natural primary keys** (`reservoir_id` + a date/timestamp) so pipeline **upserts are idempotent** (`ON CONFLICT … DO UPDATE`, FR-DE-6, §4.3). No surrogate serials on the upsert path.
- Reference/config tables (rating curves, predictions, release risk, alerts, model versions, users) get a surrogate **`uuid` PK** (`gen_random_uuid()`), with a separate unique natural key where one exists.

### 4.3 Timezone policy
- **Canonical date = IST calendar date** (`DATE`) for everything joined into the ABT (bulletins are IST; SAR/forcing UTC are mapped to the IST date they fall on — FR-ABT-2). Contract conventions §"Conventions".
- **Event/audit timestamps** (`run_timestamp`, `triggered_at`, `created_at`, `gfs_run_cycle`) are `TIMESTAMPTZ` stored in UTC.

### 4.4 Versioning, provenance, freshness (applies to every derived table)
- `*_version` text columns: `aoi_version`, `extraction_version`, `abt_version`, `contract_version`, `model_version`, `rating_curve` `version`.
- `source_versions JSONB` — dataset/model versions per source group (GEE asset IDs + processing versions, §6.6).
- `freshness_flags JSONB` — per-source staleness (FR-DE-11, NFR-REL-6).
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()` and (where mutable) `updated_at` with a trigger.
- **Immutability:** `prediction`, `release_risk`, `alert` are append-only (audit trail, NFR-REL-5); only `alert` acknowledge/resolve columns are mutable. Enforced by a `REVOKE UPDATE/DELETE` grant for the pipeline role + an `ON UPDATE`/`ON DELETE` rule on prediction/release_risk.

### 4.5 Partitioning & retention (§6.5, NFR-SCALE-1)
- Pilot volume is modest (3 reservoirs × daily grid × ~11 yrs ≈ 12k ABT rows; weekly bulletins ≈ 600 rows). **Native range partitioning is deferred but designed-in.** We create the high-churn time-series tables (`analytical_base_table`, `catchment_forcing`, `forecast_forcing`, `prediction`, `release_risk`) as **declaratively partitionable by `RANGE` on the date/issue_date column**, with a single default partition initially, so onboarding many reservoirs or years only requires `ATTACH PARTITION` migrations — no rewrite.
- **Retention:** all observations, ABT snapshots, predictions, and alerts are **retained indefinitely** (trend analysis, retraining, audit — §6.5, NFR-REL-5). No TTL deletion in v1; we add a `prediction` archival partition path for >2-year-old superseded runs as a future migration. ABT versions are retained for reproducibility (FR-ABT-4); old versions can be moved to a cold partition, never dropped.

---

## 5. Full table-by-table schema (centerpiece)

Naming: snake_case singular tables. Geometry SRID 4326 throughout. `→ contract` marks columns mirrored from the frozen contract.

### 5.1 `reservoir` (config-driven core)

| Column | Type | Key/Constraint | Notes |
| --- | --- | --- | --- |
| `reservoir_id` | `text` | PK | slug; FK target everywhere |
| `name` | `text` | NOT NULL UNIQUE | e.g. "Gobind Sagar (Bhakra Dam)" |
| `basin` | `text` | NOT NULL | Sutlej / Beas / Ravi |
| `dam_point` | `geometry(Point,4326)` | NOT NULL | seed coordinate (FR-RS-1) |
| `frl_m` | `numeric(8,3)` | NOT NULL, CHECK > 0 | Full Reservoir Level (m) |
| `live_capacity_bcm` | `numeric(10,4)` | NOT NULL, CHECK > 0 | live capacity at FRL; **time-varying** — current value; history in `reservoir_capacity_history` |
| `aoi_geom` | `geometry(MultiPolygon,4326)` | NOT NULL | AOI polygon (FR-RS-1) |
| `aoi_version` | `text` | NOT NULL | versioned GeoJSON config |
| `catchment_geom` | `geometry(MultiPolygon,4326)` | NULL | upstream contributing area (FR-DE-7); NULL until delineated |
| `catchment_version` | `text` | NULL | |
| `orbit_relative` | `int` | NOT NULL | fixed relative orbit (FR-RS-1) |
| `pass_direction` | `text` | NOT NULL, CHECK IN ('ASC','DESC') | fixed pass (FR-RS-1) |
| `release_thresholds` | `jsonb` | NOT NULL | per-level fill-%/level bands: `{watch:{pct,level_m}, warning:{…}, imminent:{…}}` (FR-ML-3) |
| `rating_curve_config` | `jsonb` | NULL | fit hyperparams / overrides; active curve lives in `rating_curve` |
| `is_active` | `bool` | NOT NULL DEFAULT true | |
| `created_at`/`updated_at` | `timestamptz` | NOT NULL | |

Indexes: `GIST(aoi_geom)`, `GIST(catchment_geom)`, `GIST(dam_point)`.
Rule curve (seasonal target levels) is the bulletin **Normal Storage** proxy (ADR-0002); stored per-date as `normal_storage_pct` in `ground_truth`/ABT rather than as a separate curve table, since it is data-derived not an official schedule.

### 5.2 `reservoir_capacity_history` (sedimentation, §10)

| Column | Type | Key | Notes |
| --- | --- | --- | --- |
| `reservoir_id` | `text` | PK, FK → reservoir | |
| `valid_from` | `date` | PK | capacity/FRL effective date |
| `live_capacity_bcm` | `numeric(10,4)` | NOT NULL CHECK>0 | |
| `frl_m` | `numeric(8,3)` | NOT NULL | |
| `source` | `text` | NOT NULL | bulletin / re-survey |
| `created_at` | `timestamptz` | NOT NULL | |

Lets rating curves and capacity carry a validity date and be periodically re-fit (§10 assumption). Current row is denormalised onto `reservoir` for hot reads.

### 5.3 `observation` (Remote-Sensing → DE) — mirrors contract §1

One row per SAR acquisition over an AOI. **PK `(reservoir_id, acquisition_date)`** → idempotent upsert.

| Column | Type | Null | → contract |
| --- | --- | --- | --- |
| `reservoir_id` | `text` FK | no | ✓ |
| `acquisition_date` | `date` (IST) | no (PK) | ✓ |
| `surface_area` | `double precision` (km²) | no | ✓ true-area, never pixel counts |
| `area_confidence` | `real` (0–1) | no | ✓ CHECK 0..1 |
| `derived_volume` | `double precision` (BCM) | yes | ✓ NULL until curve exists |
| `derived_level` | `double precision` (m) | yes | ✓ |
| `water_mask_ref` | `text` | no | ✓ URI/key to mask raster |
| `extraction_method` | `text` | no | ✓ kmeans/otsu/unet/**stub** |
| `extraction_version` | `text` | no | ✓ |
| `scene_ids` | `text[]` | no | ✓ provenance |
| `orbit_relative` | `int` | no | ✓ |
| `pass_direction` | `text` CHECK IN('ASC','DESC') | no | ✓ |
| `aoi_version` | `text` | no | ✓ |
| `layover_shadow_fraction` | `real` (0–1) | no | ✓ CHECK 0..1 |
| `processing_params` | `jsonb` | no | ✓ |
| `created_at` | `timestamptz` | no | provenance |

Optional `water_mask_geom geometry(MultiPolygon,4326)` for served GeoJSON overlay (FR-API-2) — populated only when the vector footprint is small enough; otherwise served from `water_mask_ref` raster. Indexes: PK; `(reservoir_id, acquisition_date DESC)`; `GIST(water_mask_geom)` partial WHERE NOT NULL. Constraints: `surface_area >= 0`.

### 5.4 `ground_truth` (bulletins; §6.2) — bootstrap corpus only (ADR-0005)

**PK `(reservoir_id, date)`**.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `reservoir_id` | `text` FK | no | |
| `date` | `date` (IST) | no (PK) | bulletin date |
| `level_m` | `numeric(8,3)` | yes | CURRENT RESERVOIR LEVEL (M) |
| `live_storage_bcm` | `numeric(10,4)` | yes | CURRENT LIVE STORAGE (BCM) |
| `pct_filled` | `numeric(6,3)` | yes | CHECK 0..110 (FR-DE-4) |
| `frl_m` | `numeric(8,3)` | no | denormalised for as-of |
| `live_capacity_bcm` | `numeric(10,4)` | no | |
| `normal_storage_pct` | `numeric(6,3)` | yes | rule-curve proxy (ADR-0002) |
| `benefits_irr_cca` | `numeric` | yes | §6.2 |
| `benefits_hydel_mw` | `numeric` | yes | §6.2 |
| `source_pdf` | `text` | yes | provenance |
| `row_quality` | `text` CHECK IN('ok','low_confidence','quarantine') | no DEFAULT 'ok' | FR-DE-2/4 |
| `created_at` | `timestamptz` | no | |

Quarantined rows kept, not deleted (FR-DE-2, NFR-TEST-1). Data-quality CHECKs: `level_m <= frl_m * 1.02` tolerance (FR-DE-4), `live_storage_bcm <= live_capacity_bcm * 1.05`. Violations route to quarantine via the loader, so CHECKs are advisory triggers, not hard constraints that would reject the whole batch — implemented as a `row_quality` setting trigger + a hard CHECK only on physically-impossible values (negatives).

### 5.5 `ground_truth_match` (FR-GT-1…3) — AC-2 evidence

**PK `(reservoir_id, gt_date, extraction_version)`** (a GT date may be re-matched by a new extractor).

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `reservoir_id` | `text` FK | no | |
| `gt_date` | `date` | no (PK, FK→ground_truth) | bulletin date |
| `acquisition_date` | `date` | no | matched scene date |
| `time_gap_days` | `int` | no | CHECK abs ≤ tolerance N (FR-GT-1) |
| `scene_ids` | `text[]` | no | |
| `extracted_area` | `double precision` (km²) | no | |
| `area_confidence` | `real` (0–1) | no | |
| `extraction_method` | `text` | no | |
| `extraction_version` | `text` | no (PK) | |
| `rating_curve_version` | `text` | yes | curve used for conversion |
| `derived_volume` | `double precision` (BCM) | yes | |
| `derived_level` | `double precision` (m) | yes | |
| `derived_pct_filled` | `numeric(6,3)` | yes | |
| `residual_vs_ground_truth` | `double precision` (%) | yes | FR-DE-5, FR-GT-3 |
| `is_weak_label` | `bool` | no DEFAULT false | high-confidence low-residual → U-Net label (FR-GT-6) |
| `created_at` | `timestamptz` | no | |

Index `(reservoir_id, gt_date)`. This table + `rating_curve` is the AC-2 evidence (matched, converted, residual computed, versioned).

### 5.6 `rating_curve` (FR-GT-4, ADR-0004) — blended

Surrogate `uuid` PK + unique `(reservoir_id, version)`.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` PK | no | |
| `reservoir_id` | `text` FK | no | |
| `version` | `text` | no | unique with reservoir_id |
| `fit_type` | `text` CHECK IN('empirical','dem_prior','blended') | no | ADR-0004 |
| `area_to_storage_params` | `jsonb` | no | coeffs/spline knots area→BCM |
| `area_to_level_params` | `jsonb` | no | area→m |
| `curve_points` | `jsonb` | yes | tabulated (area, storage, level) for plotting |
| `frl_anchor` | `jsonb` | no | area/storage/level at FRL |
| `observed_range` | `jsonb` | no | `{area_min,area_max,…}` valid empirical range |
| `extrapolated_range` | `jsonb` | yes | above observed max → FRL (DEM-governed) |
| `dem_epoch_waterline_m` | `numeric(8,3)` | yes | ADR-0004 step 1 |
| `dem_asset_id` | `text` | yes | e.g. `COPERNICUS/DEM/GLO30` |
| `fit_metrics` | `jsonb` | no | MAE/RMSE on pct_filled, overlap divergence |
| `valid_from` | `date` | no | sedimentation validity (§10) |
| `is_active` | `bool` | no DEFAULT false | one active per reservoir |
| `mlflow_run_id` | `text` | yes | reproducibility (NFR-MNT-2) |
| `created_at` | `timestamptz` | no | |

Partial unique index `(reservoir_id) WHERE is_active` → exactly one active curve per reservoir.

### 5.7 `catchment_forcing` (FR-DE-7…11) — mirrors ABT forcing block

**PK `(reservoir_id, date)`**, range-partitionable on `date`.

| Column | Type | Unit | Null | → contract |
| --- | --- | --- | --- | --- |
| `reservoir_id` | `text` FK | — | no | |
| `date` | `date` (IST) | — | no (PK) | |
| `catchment_precip` | `double precision` | mm/day | yes | ✓ FR-DE-8 |
| `antecedent_precip_index` | `double precision` | mm | yes | ✓ |
| `snow_cover_area` | `real` | 0–1 | yes | ✓ FR-DE-9, CHECK 0..1 |
| `swe` | `double precision` | mm | yes | ✓ |
| `degree_day_melt` | `double precision` | mm/day | yes | ✓ |
| `source_versions` | `jsonb` | — | no | dataset versions (§6.6) |
| `freshness_flags` | `jsonb` | — | no | FR-DE-11 |
| `created_at` | `timestamptz` | — | no | |

### 5.8 `forecast_forcing` (FR-DE-10, contract §3) — horizon-keyed

**PK `(reservoir_id, issue_date, horizon)`**, range-partitionable on `issue_date`.

| Column | Type | Unit | Null | → contract |
| --- | --- | --- | --- | --- |
| `reservoir_id` | `text` FK | — | no (PK) | ✓ |
| `issue_date` | `date` (IST) | — | no (PK) | ✓ as-of date knowable |
| `horizon` | `int` | days | no (PK) | ✓ CHECK 1..14 |
| `forecast_precip` | `double precision` | mm/day | yes | ✓ valid at issue_date+horizon |
| `forecast_degree_day_melt` | `double precision` | mm/day | yes | ✓ |
| `gfs_run_cycle` | `timestamptz` | — | no | ✓ provenance (00/06/12/18Z) |
| `source_versions` | `jsonb` | — | no | ✓ |
| `created_at` | `timestamptz` | — | no | |

### 5.9 `analytical_base_table` (FR-ABT-1…5, AC-10) — mirrors contract §2

**PK `(reservoir_id, date, abt_version)`** on a continuous daily IST grid. Adding `abt_version` to the PK is the **one deliberate extension** beyond the contract's `(reservoir_id, date)` grain: it lets multiple immutable ABT snapshots coexist (FR-ABT-4 / AC-10 reproducibility) without clobbering. The "current" view exposes the contract's `(reservoir_id, date)` grain. Range-partitionable on `date`.

Keys & alignment:

| Column | Type | Unit | Null | → contract |
| --- | --- | --- | --- | --- |
| `reservoir_id` | `text` FK | — | no | ✓ |
| `date` | `date` (IST) | — | no | ✓ continuous daily |
| `abt_version` | `text` | — | no | ✓ snapshot (in PK) |
| `days_since_bulletin` | `int` | days | no | ✓ recency |
| `days_since_acquisition` | `int` | days | no | ✓ recency |

Ground truth (populated on bulletin dates):

| Column | Type | Unit | Null |
| --- | --- | --- | --- |
| `gt_level` | `double precision` | m | yes |
| `gt_live_storage_bcm` | `double precision` | BCM | yes |
| `gt_pct_filled` | `double precision` | % | yes |
| `frl` | `double precision` | m | no |
| `live_capacity_bcm` | `double precision` | BCM | no |
| `normal_storage_pct` | `double precision` | % | yes (rule-curve proxy) |

Satellite-derived (populated on acquisition dates):

| Column | Type | Unit | Null |
| --- | --- | --- | --- |
| `surface_area` | `double precision` | km² | yes |
| `area_confidence` | `real` | 0–1 | yes |
| `derived_volume` | `double precision` | BCM | yes |
| `derived_level` | `double precision` | m | yes |
| `extraction_method` | `text` | — | yes |

Catchment forcing (native daily): `catchment_precip`, `antecedent_precip_index`, `snow_cover_area`, `swe`, `degree_day_melt` — types/units exactly as §5.7.

Provenance, quality & target:

| Column | Type | Unit | Null | Notes |
| --- | --- | --- | --- | --- |
| `is_extrapolated` | `bool` | — | no | FR-ABT-5, derived value above observed max |
| `residual_vs_ground_truth` | `double precision` | % | yes | FR-DE-5 |
| `source_versions` | `jsonb` | — | no | |
| `freshness_flags` | `jsonb` | — | no | |
| `row_quality` | `text` CHECK IN('ok','low_confidence','quarantine') | — | no | FR-DE-4 |
| `abt_version` (also PK) | `text` | — | no | FR-ABT-4 |
| `created_at` | `timestamptz` | — | no | |

Point-in-time correctness is enforced at **build time** (§7), not by a column; the table holds only knowable-at-`date` values. Forecast forcing is **NOT** denormalised here — ML joins `forecast_forcing` on `reservoir_id, issue_date = date` (contract §3, v2 change). Indexes: PK; `(reservoir_id, date)` partial WHERE `abt_version = <current>`; `(abt_version)`.

### 5.10 `model_version` (mirror of MLflow registry; FR-ML-4)

Surrogate `uuid` PK, unique `(model_name, version)`. Columns: `model_name text`, `version text`, `mlflow_run_id text`, `model_stage text CHECK IN('staging','production','archived')`, `trained_on_abt_version text` (FR-ABT-4 link), `metrics jsonb`, `created_at`. Lets `prediction`/`release_risk` FK a stable model identity without coupling to MLflow availability.

### 5.11 `prediction` (FR-ML-2, FR-ML-5) — append-only

**PK `(reservoir_id, run_timestamp, horizon_date)`**; range-partitionable on `run_timestamp::date`.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `reservoir_id` | `text` FK | no | |
| `run_timestamp` | `timestamptz` | no (PK) | inference run |
| `horizon_date` | `date` | no (PK) | target IST date (1–14d) |
| `predicted_level_m` | `double precision` | yes | |
| `predicted_volume_bcm` | `double precision` | yes | |
| `predicted_pct_filled` | `double precision` | yes | |
| `interval_low` / `interval_high` | `double precision` | yes | conformal interval (ADR-0006) |
| `model_version` | `text` FK → model_version | no | provenance (NFR-REL-5) |
| `input_abt_version` | `text` | no | reproducibility (FR-ABT-4) |
| `created_at` | `timestamptz` | no | |

### 5.12 `release_risk` (FR-ML-3, primary) — append-only

**PK `(reservoir_id, run_timestamp)`**.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `reservoir_id` | `text` FK | no | |
| `run_timestamp` | `timestamptz` | no (PK) | |
| `release_probability` | `real` CHECK 0..1 | no | |
| `risk_level` | `text` CHECK IN('Low','Watch','Warning','Imminent') | no | §8.3 |
| `estimated_lead_time_days` | `real` | yes | |
| `contributing_factors` | `jsonb` | no | explainability (§8.3) |
| `model_version` | `text` FK | no | |
| `input_abt_version` | `text` | no | |
| `created_at` | `timestamptz` | no | |

### 5.13 `alert` (FR-UI-6, AC-11, NFR-REL-5) — in-app + audit history

Surrogate `uuid` PK.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` PK | no | |
| `reservoir_id` | `text` FK | no | |
| `alert_type` | `text` CHECK IN('flood_release','approaching_frl','rapid_rise','data_quality') | no | §6.3 |
| `severity` | `text` CHECK IN('info','watch','warning','imminent') | no | |
| `triggered_at` | `timestamptz` | no | |
| `message` | `text` | no | |
| `contributing_factors` | `jsonb` | yes | |
| `release_risk_id` | `uuid` FK → release_risk via (reservoir_id,run_timestamp) | yes | links to risk (AC-11) |
| `acknowledged_by` | `uuid` FK → app_user | yes | mutable |
| `acknowledged_at` | `timestamptz` | yes | mutable |
| `resolved_at` | `timestamptz` | yes | mutable |
| `created_at` | `timestamptz` | no | |

Only ack/resolve columns are UPDATE-able; trigger blocks edits to the rest (immutable history). Index `(reservoir_id, triggered_at DESC)`, partial index `WHERE acknowledged_at IS NULL` (open alerts).

### 5.14 RBAC: `app_user`, `role`, `user_role` (§3, §7.5, NFR-SEC-1)

`app_user`: `id uuid PK`, `email text UNIQUE NOT NULL`, `hashed_password text`, `full_name text`, `is_active bool`, `created_at`, `last_login_at`.
`role`: `id uuid PK`, `name text UNIQUE CHECK IN('disaster_mgmt','dam_operator','analyst','admin','public_viewer')` — the five §3 roles.
`user_role`: `user_id uuid FK`, `role_id uuid FK`, PK `(user_id, role_id)`.
(Optional `permission` + `role_permission` if fine-grained perms are needed beyond the five roles; deferred unless the API team requires it.)

### 5.15 `pipeline_run` (NFR-REL-2, FR-API-5) — observability

`id uuid PK`, `pipeline text CHECK IN('remote_sensing','data_engineering','ml')`, `reservoir_id text FK NULL`, `status text CHECK IN('running','success','failed','quarantined')`, `started_at`, `finished_at`, `row_counts jsonb`, `error jsonb`, `triggered_by text`, `contract_version text`. Queryable run history; idempotency keyed by `(pipeline, reservoir_id, acquisition_date)` recorded in `row_counts`/metadata (§4.3).

---

## 6. ABT design & point-in-time approach (AC-10)

1. **Grain & calendar.** Continuous daily IST grid per reservoir (contract §2). A `generate_series` of dates per reservoir is the spine; GT and SAR columns are left-joined and `NULL` where absent, with `days_since_*` recency carried (NFR-REL-6 graceful degradation signal).
2. **As-of (point-in-time) joins (FR-ABT-3).** The ABT builder is a deterministic SQL/Python transform that, for each `(reservoir_id, date)`, pulls **only rows with `date'≤ date`**:
   - Ground truth: nearest bulletin with `date' ≤ date` within tolerance (FR-ABT-2 nearest-match), never a future bulletin.
   - SAR: nearest `observation` with `acquisition_date ≤ date`.
   - Forcing: same-day `catchment_forcing` (native daily).
   - Forecast forcing stays in `forecast_forcing` keyed by `issue_date = date`, built from the GFS run issued `≤ issue_date` (contract §3). No reanalysis backfill — that would leak the future.
3. **No-leakage guarantee.** Enforced by construction (the builder's `WHERE date' ≤ date` and "GFS issued ≤ date" predicates) **and** by a test harness (§9) that asserts every populated cell's source timestamp ≤ the row date. This is the AC-10 leakage test.
4. **Versioned snapshots (FR-ABT-4).** Each build writes rows tagged with a new `abt_version` (e.g. `abt_2026_06_16_v1`), and the `model_version.trained_on_abt_version` / `prediction.input_abt_version` columns pin every model run to the exact snapshot it saw (recorded alongside the MLflow run). Snapshots are immutable and retained.
5. **Materialisation strategy.** The ABT is a **physical derived table** (not a view): models need stable, snapshot-able, indexable data and reproducibility (FR-ABT-4), which a `MATERIALIZED VIEW` refresh cannot version cleanly. The builder is an idempotent upsert keyed by `(reservoir_id, date, abt_version)`. A convenience view `abt_current` exposes the latest `abt_version` at the contract's `(reservoir_id, date)` grain for serving.
6. **Quality flags (FR-ABT-5).** `row_quality`, `is_extrapolated`, `freshness_flags`, `residual_vs_ground_truth` per row so ML can weight/exclude (`quarantine` rows excluded from training).

---

## 7. Migrations & seeding plan

- **Alembic** in `db/migrations/`; autogenerate from `core/models/` then hand-edit (PostGIS DDL, partitioning, partial indexes, triggers are not autogenerated reliably).
- **Migration 0001 — extensions & enums:** `CREATE EXTENSION postgis; CREATE EXTENSION "uuid-ossp"/pgcrypto;` plus enum-equivalent CHECKs (we use CHECK constraints over native ENUMs for cheap evolution).
- **0002 — reservoir + capacity history + RBAC** (no FK dependents yet).
- **0003 — observation, ground_truth, catchment_forcing, forecast_forcing** (the contract tables; bump nothing, mirror v2).
- **0004 — ground_truth_match, rating_curve** (AC-2 path).
- **0005 — analytical_base_table + abt_current view** (AC-10).
- **0006 — model_version, prediction, release_risk, alert** (with append-only triggers).
- **0007 — pipeline_run + indexes + grants** (least-privilege roles: `app_ro`, `pipeline_rw`, `migrator`; NFR-SEC-3).
- **Partitioning migrations** are separate and additive (`ATTACH PARTITION`), kept out of the base schema so the pilot runs single-partition.
- **Seeding:** an idempotent `db/seed.py` loads the 3 pilot reservoirs (slugs `gobind_sagar`, `pong`, `thein`) with dam points, FRL, capacity, orbit/pass, AOI/catchment versions, and `release_thresholds`. GT bulletins seeded from the `dataExtractor` CSV via the DE loader (quarantine on violation). Roles seeded (5 §3 roles) + one bootstrap admin from env (NFR-SEC-2). `extraction_method='stub'` observations can be seeded so DE/ML start before real SAR lands (contract stub rule).
- **Contract-version guard:** a CI check asserts the SQLAlchemy `Observation`/`AnalyticalBaseTable`/`ForecastForcing` columns match `docs/contracts/observation-and-abt.md` v2 exactly; changing either requires bumping `contract_version` (ADR-0003).

---

## 8. Task breakdown (sequenced)

| ID | Task | Acceptance check |
| --- | --- | --- |
| **T-01** | Repo scaffolding: `core/` (models, schemas, db session), `db/` (alembic env, migrations), `uv` deps (sqlalchemy 2, alembic, geoalchemy2, psycopg, pydantic 2). Docker-compose Postgres+PostGIS service. | `alembic upgrade head` runs on clean checkout against the compose DB (AC-8). |
| **T-02** | Migration 0001–0002: extensions, `reservoir`, `reservoir_capacity_history`, RBAC tables. GeoAlchemy2 geometry columns @4326. | PostGIS enabled; `\d reservoir` shows GIST indexes; geometry SRID = 4326. |
| **T-03** | Migration 0003: `observation`, `ground_truth`, `catchment_forcing`, `forecast_forcing` — **column-exact to contract v2**. | Contract-parity test passes (column name/type/null match). Upsert idempotency test on PKs. |
| **T-04** | Migration 0004: `ground_truth_match`, `rating_curve` (blended fields, active-curve partial unique, valid_from). | Insert a matched pair + active blended curve; residual stored; second active curve rejected. **(AC-2 schema ready.)** |
| **T-05** | Migration 0005: `analytical_base_table` (+ `abt_current` view) and the **point-in-time ABT builder** (idempotent, versioned). | Leakage test: every populated cell's source date ≤ row date; rebuild with new `abt_version` coexists. **(AC-10.)** |
| **T-06** | Migration 0006: `model_version`, `prediction`, `release_risk`, `alert` + append-only triggers + ack/resolve mutability. | UPDATE/DELETE on prediction blocked; alert ack succeeds; risk_level/severity CHECKs enforced. |
| **T-07** | Migration 0007: `pipeline_run`, all secondary indexes, least-privilege roles & grants. | `pipeline_rw` cannot UPDATE prediction; `app_ro` cannot write; spatial/time indexes present. |
| **T-08** | Pydantic v2 schemas mirroring every model (`core/schemas/`), incl. Geo types (GeoJSON via `shapely`/`geojson-pydantic`). | Round-trip a row → Pydantic → JSON; ORM-mode (`from_attributes`) works. |
| **T-09** | Seeding (`db/seed.py`): 3 reservoirs, roles, admin, GT bulletin load with quarantine, optional stub observations. | Seed is idempotent (re-run no-ops); 3 reservoirs present; malformed GT row quarantined not rejected. |
| **T-10** | Data-quality constraint suite & triggers (FR-DE-4): range/consistency CHECKs, quarantine routing trigger, freshness defaults. | Out-of-range `pct_filled` → `row_quality='quarantine'`; negative area hard-rejected. |
| **T-11** | Schema/constraint test suite + contract-parity CI gate + partitioning migration template. | All tests green in CI (AC-12 schema portion); `ATTACH PARTITION` template applies cleanly. |
| **T-12** | Backup/retention runbook + automated `pg_dump`/PITR config (compose volume + scheduled dump). | Documented RPO/RTO; restore-from-dump smoke test passes (NFR-REL-4). |

Sequence: T-01 → T-02 → T-03 (unblocks DE/ML against the contract) → T-04/T-05 in parallel → T-06 → T-07 → T-08/T-09/T-10 → T-11/T-12.

---

## 9. Interfaces / contracts exposed

**Canonical tables** (other teams import these names; do not rename without an ADR + contract bump):
`reservoir`, `reservoir_capacity_history`, `observation`, `ground_truth`, `ground_truth_match`, `rating_curve`, `catchment_forcing`, `forecast_forcing`, `analytical_base_table` (+ `abt_current` view), `model_version`, `prediction`, `release_risk`, `alert`, `app_user`/`role`/`user_role`, `pipeline_run`.

**Module paths:**
- SQLAlchemy 2.x models: `core/models/<entity>.py` (e.g. `core.models.observation.Observation`, `core.models.abt.AnalyticalBaseTable`), shared `Base` in `core/models/base.py`.
- Pydantic v2 schemas: `core/schemas/<entity>.py` (e.g. `core.schemas.abt.AnalyticalBaseTableRow`), with `Create`/`Read`/`Upsert` variants.
- DB session/engine: `core/db/session.py`.
- Frozen contract source of truth: `docs/contracts/observation-and-abt.md` (`contract_version: 2`) — the SQLAlchemy models for `Observation`/`AnalyticalBaseTable`/`ForecastForcing` are a 1:1 mirror; CI enforces parity.

---

## 10. Testing (schema/constraint)

- **Contract-parity test** (T-03/T-11): introspect SQLAlchemy metadata for the three contract tables vs the markdown table → assert exact column set, types, nullability. Fails CI on drift (ADR-0003).
- **Constraint tests:** CHECKs (`pct_filled` 0–110, `area_confidence`/`snow_cover_area` 0–1, `horizon` 1–14, enum-CHECKs); negative area rejected; one-active-rating-curve partial unique; FK integrity.
- **Idempotency tests:** double-upsert on every natural-key table is a no-op / clean update (FR-DE-6).
- **Point-in-time / leakage test (AC-10):** build ABT for a date, assert no source cell has a timestamp > row date; assert forecast columns come from a GFS run ≤ issue_date.
- **Append-only/audit tests (NFR-REL-5):** UPDATE/DELETE on `prediction`/`release_risk` blocked; alert ack/resolve allowed, body immutable.
- **Spatial tests:** geometry SRID = 4326; AOI/catchment are valid (`ST_IsValid`); GIST indexes exist and are used (EXPLAIN).
- **Migration round-trip:** `upgrade head` then `downgrade base` clean on a throwaway DB (CI).
- Frameworks: `pytest` + `testcontainers`/compose Postgres+PostGIS; aligns with NFR-TEST-2 (ABT-join tests).

---

## 11. Backup & retention alignment (NFR-REL-4, §6.5)

- **Backups:** nightly `pg_dump` (logical) to object storage + WAL archiving for **PITR** in the self-hosted deployment. Compose service ships a `pg-backup` sidecar. Documented **RPO ≤ 24h (logical) / ≤ 5 min (WAL PITR), RTO ≤ 1h**.
- **Retention:** observations, ABT snapshots, predictions, release-risk, and alerts retained **indefinitely** (trend/retraining/audit — §6.5, NFR-REL-5). Old ABT versions and >2-yr superseded predictions move to cold partitions (future migration), never dropped. The audit trail (predictions/alerts/model_version) is immutable by grant + trigger.

---

## 12. Risks & open decisions

| # | Risk / open decision | Who it affects | Proposed default |
| --- | --- | --- | --- |
| R-1 | **ABT PK extension** (`+abt_version`) vs contract's `(reservoir_id, date)` grain. | ML, DE | Keep `abt_version` in PK; expose `abt_current` view at contract grain. **Needs ML sign-off** — does any ML query assume a single row per (reservoir,date)? |
| R-2 | **Hard CHECK vs quarantine** for data-quality (FR-DE-4): a hard CHECK rejects the whole batch; quarantine keeps the row flagged. | DE | Hard-reject only physically-impossible values (negatives); route soft violations to `row_quality='quarantine'` via trigger. |
| R-3 | **Water-mask vector vs raster** storage: large multipolygons bloat the DB. | RS, API | Store `water_mask_ref` (raster URI) always; optional simplified `water_mask_geom` only for served overlays. Confirm with API team the GeoJSON size budget (FR-API-2). |
| R-4 | **Native partitioning timing.** Pilot volume doesn't need it; onboarding many reservoirs will. | DE, ops | Ship single-partition, partition-ready DDL; add `ATTACH PARTITION` migrations when fleet grows (NFR-SCALE-1). |
| R-5 | **MLflow as source of truth vs `model_version` mirror.** Double-bookkeeping risk. | ML | Mirror minimal registry identity in `model_version` so prediction provenance survives MLflow downtime; MLflow remains authoritative for artifacts. |
| R-6 | **Time-varying capacity** (sedimentation, §10): which capacity does the ABT denormalise — as-of-date or current? | ML, DE | ABT uses the capacity **valid at that `date`** (point-in-time, from `reservoir_capacity_history`); serving uses current. Confirm with ML. |
| R-7 | **`numeric` vs `double precision`** mismatch: contract specifies `float` for ABT/observation; bulletins use `numeric` for exactness. | DE, ML | Follow contract `float` (`double precision`) for contract tables; `numeric` only for raw `ground_truth` source fidelity. |
| R-8 | RBAC granularity: 5 roles vs fine-grained permissions. | API | Start with 5 §3 roles; add `permission` table only if API needs per-endpoint scopes. |

**Mapping to AC:** **AC-2** satisfied by `ground_truth_match` (matched pairs, time_gap, residuals, versioned extraction) + `rating_curve` (blended, observed/extrapolated range, active, MLflow-linked). **AC-10** satisfied by `analytical_base_table` (versioned snapshots, point-in-time builder, quality flags) + the leakage test + `input_abt_version` provenance on every model run. **AC-11** via `alert` (timestamped, acknowledgeable, immutable history, linked to `release_risk`). **AC-8/AC-12** via clean-checkout migrations + schema tests in CI. **NFR-REL-4/5** via backups + append-only audit tables.
