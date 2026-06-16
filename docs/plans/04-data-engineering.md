# Plan 04 — Data Engineering (ETL) Pipeline

**Owner:** Data Engineering track
**Status:** Planning (planning-only document — no application code here)
**Stack:** Python · `uv` · `geemap` + `xee` (GEE) · `pandera` + Great Expectations · PostgreSQL + PostGIS via DB-team SQLAlchemy models · **Prefect 2** orchestration
**Code root:** `pipelines/data_engineering/` · flows in `orchestration/`
**Frozen contract:** [`docs/contracts/observation-and-abt.md`](../contracts/observation-and-abt.md) (`contract_version: 2`)

---

## 1. Scope & owned requirements

This pipeline is the **silver→gold** stage of the medallion flow. It consumes Remote-Sensing `Observation` rows + historical bulletins, fuses and validates them, generates catchment hydromet forcing, and **emits the Unified Analytical Base Table (ABT)** — the single dataset the ML pipeline trains and infers on.

| Req ID | Ownership |
| --- | --- |
| **FR-DE-1** | Ingest historical ground-truth bulletin timeseries → gold schema. Source = companion `dataExtractor` CSV (`data/historical/reservoir_timeseries.csv`, already unified by `pipelines/build_unified_dataset.py`). |
| **FR-DE-2** | Clean/standardise units, names, dates; dedup; reject/quarantine malformed rows. |
| **FR-DE-3** | **Fuse** satellite estimates with ground truth on `(reservoir, nearest date)`. |
| **FR-DE-4** | Data-quality gates: fill% ∈ [0,110], area ≥ 0, level ≤ FRL + tol; flag anomalies. |
| **FR-DE-5** | Compute estimate-vs-ground-truth **residuals**. |
| **FR-DE-6** | Idempotent upserts into PostgreSQL; load/audit log. |
| **FR-DE-7** | **Catchment delineation** — MERIT Hydro `upa`/`pyflwdir` trace from dam point, HydroBASINS scaffold, validate vs published areas, persist PostGIS polygon. |
| **FR-DE-8** | Precip ingestion + catchment aggregation (ERA5-Land lead, IMERG cross-check, CHIRPS tertiary); lagged precip + antecedent precip index. |
| **FR-DE-9** | Snow & temperature ingestion (MODIS NDSI SCA, ERA5-Land/GLDAS SWE+melt+T2m); degree-day melt + SCA trend. |
| **FR-DE-10** | **NOAA GFS forecast forcing** — forecast precip + forecast degree-day melt over 1–14d; archived reforecasts for train/serve consistency. |
| **FR-DE-11** | Assemble per-reservoir per-date **catchment-forcing table**, time-aligned, with provenance + freshness flags; idempotent upsert. |
| **FR-DE-12** | **Produce the ABT (§6.7)** as gold output — join FR-DE-3 fused storage with FR-DE-11 forcing per FR-ABT-1..5. |
| **FR-ABT-1..5** | Canonical join · alignment policy (nearest-match + resample + IST/UTC) · point-in-time correctness · versioned/reproducible · quality+coverage flags. |
| **NFR-TEST-1** | Automated data-validation on every run; quarantine, never silently propagate. |
| **§4.3** | Idempotent, observable, automated; RS→DE→ML trigger chain (DE owns the DE link). |

**Out of scope (other tracks):** SAR water extraction + `Observation` emission (RS, plan 03); rating-curve *fitting* and the forecaster/release model (ML, plan 05); DB schema/SQLAlchemy models + Alembic migrations (DB team). DE **writes to** the canonical entity names the DB team owns; it does not define them.

---

## 2. Upstream dependencies

| Dependency | Provider | Form / contract |
| --- | --- | --- |
| **`Observation` rows** | Remote-Sensing pipeline | Frozen `Observation` schema (contract §1), one row per SAR acquisition. **Stub rule:** until real SAR lands, synthetic rows with `extraction_method='stub'` (inverted rough rating curve) — DE must treat stubs as first-class and filterable. |
| **Bulletin CSV** | `dataExtractor` (companion) → `build_unified_dataset.py` | `data/historical/reservoir_timeseries.csv`, §6.2 schema, weekly, IST dates, 2015-07→2026-04, 3 reservoirs (~583 rows). **Closed loop (ADR-0005):** this is the *entire* ground-truth corpus; never refreshed in production. |
| **DB schema (SQLAlchemy models)** | DB team | Canonical entities: `Reservoir` (incl. dam-point seed, FRL, capacity, `normal_storage` proxy), `CatchmentForcing`, `Observation`, `GroundTruth`, `GroundTruthMatch`, `AnalyticalBaseTable`, plus a `ForecastForcing` table (contract §3). DE upserts; DB team owns DDL + PostGIS geometry columns. |
| **GEE layers** | Google Earth Engine (via `geemap`/`xee`) | Per §6.6 catalogue (asset IDs below). DE needs a service-account credential (`NFR-SEC-2`, env/secret store). |
| **Reservoir static config** | `pipelines/build_unified_dataset.py` `REGISTRY` + AOI GeoJSON (RS, FR-RS-1) | Dam-point seeds, FRL, capacity, aliases. Catchment delineation needs the dam point; forcing aggregation needs the catchment polygon DE itself produces. |

**GEE asset IDs used (FR-DE-7..10):**

| Purpose | Asset | Bands/vars | Priority |
| --- | --- | --- | --- |
| Catchment basins | `WWF/HydroSHEDS/v1/Basins/hybas_*` (L1–L12) | basin polygons | scaffold only |
| Hydrography routing | `MERIT/Hydro/v1_0_1` | `dir`, `upa` | primary delineation |
| Precip (reanalysis) | `ECMWF/ERA5_LAND/DAILY_AGGR` | `total_precipitation_sum`, `temperature_2m`, `snow_depth_water_equivalent`, `snowmelt_sum` | **lead** |
| Precip (satellite) | `NASA/GPM_L3/IMERG_V07` | `precipitation` | cross-check |
| Precip (tertiary) | `UCSB-CHG/CHIRPS/DAILY` | `precipitation` | tertiary |
| Snow/melt land-surf | `NASA/GLDAS/V021/NOAH/G025/T3H` | `SWE_inst`, `Qsm_acc`, `Tair_f_inst` | alt SWE/melt |
| Snow-cover area | `MODIS/061/MOD10A1` | `NDSI_Snow_Cover` | primary SCA |
| Forecast forcing | `NOAA/GFS0P25` | `total_precipitation_surface`, `temperature_2m_above_ground` | forecast (archive ≥2015) |

---

## 3. Downstream consumers

- **ML pipeline (plan 05)** reads the **ABT** (`AnalyticalBaseTable`) + **`ForecastForcing`** as its sole training/inference inputs (FR-DE-12, FR-ML-2). It joins `ForecastForcing` on `reservoir_id` and `issue_date = date`.
- **Ground-truthing / rating-curve fit (FR-GT-4, ML track)** consumes `GroundTruthMatch` (the fused matched pairs DE produces) to fit per-reservoir Area↔Storage↔Level curves. DE supplies the *pairs and residuals*; ML supplies the *curve*. (Bootstrap circularity — `Observation.derived_volume/level` are NULL until a curve exists — is handled by the stub rule + a two-pass build; see §5.6.)
- **Backend API (FR-API)** reads `CatchmentForcing` freshness flags and `AnalyticalBaseTable.row_quality` for the data-freshness/staleness UI (NFR-REL-6).
- **MLflow** records the `abt_version` snapshot each ML run trains against (FR-ABT-4, AC-10).

---

## 4. Pipeline / flow design (medallion: bronze → silver → gold)

Prefect 2 constructs: each stage is a `@task` (with `retries`, `retry_delay_seconds`, `cache_key_fn` for idempotency, `tags` for concurrency limits); stages compose into `@flow`s; flows are deployed with `Deployment` + a work-pool worker in a container (§4.3). A top-level **`de_pipeline_flow`** is the trigger target of the RS→DE chain.

### Bronze (raw landing — immutable, provenance-stamped)

| Task | Reads | Writes | Notes |
| --- | --- | --- | --- |
| `ingest_bulletins` | `reservoir_timeseries.csv` | `bronze.bulletins_raw` | FR-DE-1. Load as-is + `_ingested_at`, `_source_file`, `_row_hash`. Bulletin date is **IST** (mark tz). |
| `pull_observations` | `Observation` table (RS) | (in-memory / `bronze.observations_raw`) | FR-DE-3 input. Includes stubs. |
| `pull_hydromet_raw` | GEE via `xee` (ERA5-Land, IMERG, CHIRPS, GLDAS, MODIS) clipped to catchment | `bronze.hydromet_raw/<dataset>/<reservoir>/<date>.parq` | FR-DE-8/9. **UTC** native. One subtask per (dataset × reservoir), GEE-concurrency-limited via Prefect tag. |
| `pull_gfs_raw` | GEE `NOAA/GFS0P25` (incl. archived runs) | `bronze.gfs_raw/<reservoir>/<issue>/<cycle>.parq` | FR-DE-10. Keyed by run cycle (00/06/12/18Z) for point-in-time. |

### Silver (cleaned · standardised · validated · per-domain tables)

| Task | Produces | Requirements |
| --- | --- | --- |
| `clean_bulletins` | standardised bulletin frame (canonical names, SI units, parsed IST dates, dedup by `(reservoir, ISO week)` precedence) → `GroundTruth` | FR-DE-2. Reuses `build_unified_dataset.py` cleaning logic (canonical registry, unit conversions, source precedence) — promote to a library module `de/cleaning.py`. |
| `validate_bulletins` | pass/quarantine split | FR-DE-4, NFR-TEST-1. pandera schema + GE suite (ranges, nulls, temporal continuity). Failures → `quarantine.bulletins`. |
| `delineate_catchment` (once / config-change) | `Reservoir.catchment_polygon` (PostGIS) | FR-DE-7. `pyflwdir` trace on MERIT `upa` from dam point; HydroBASINS L8–L12 scaffold; validate delineated area vs published; manual-override hook. |
| `aggregate_forcing` | `CatchmentForcing` daily rows | FR-DE-8/9/11. `xee` → `xarray` → catchment-mean reduce; antecedent index, degree-day melt, SCA fraction+trend, lagged precip. UTC→IST date mapping. |
| `build_forecast_forcing` | `ForecastForcing` `(reservoir, issue_date, horizon)` | FR-DE-10. Point-in-time GFS run ≤ issue_date, read at valid time issue+h; derive forecast degree-day melt from forecast T2m. |
| `fuse_observations_groundtruth` | `GroundTruthMatch` | FR-DE-3, FR-GT-1. Nearest-date asof-join within ±N day tolerance; record `time_gap_days`. |
| `compute_residuals` | residual fields on `GroundTruthMatch` | FR-DE-5. derived `pct_filled` − bulletin `pct_filled` (NULL until a rating curve exists). |
| `validate_forcing` | pass/quarantine | FR-DE-4, NFR-TEST-1. pandera/GE on `CatchmentForcing` + `ForecastForcing`. |

### Gold (analytics-ready — the ABT)

| Task | Produces | Requirements |
| --- | --- | --- |
| `build_abt` | `AnalyticalBaseTable` (contract §2 schema) | FR-DE-12, FR-ABT-1..5. The centerpiece algorithm in §5. |
| `validate_abt` | full GE checkpoint on ABT | AC-10, AC-12, NFR-TEST-1. Schema, grain uniqueness, point-in-time invariants, quality-flag coverage. |
| `upsert_gold` | idempotent upsert + `load_audit` row | FR-DE-6. Keyed `(reservoir_id, date)`; records `abt_version`, row counts, status. |
| `emit_ml_trigger` | Prefect run of `ml_pipeline_flow` | §4.3 trigger chain. Only on validate_abt success. |

---

## 5. ABT construction algorithm (centerpiece, FR-ABT-1..5)

**Goal:** one row per `(reservoir_id, date)` on a **continuous daily IST calendar**, joining ground truth + satellite-derived + catchment forcing, point-in-time correct, versioned, with quality flags. Exact columns are frozen in contract §2 — this section is the *build logic*.

### 5.1 Spine (continuous daily grid)

For each reservoir, generate a daily IST date index from `min(first bulletin, first acquisition, first forcing)` to `today` (serve) or `last data` (backtest). This is the ABT spine; ground-truth and SAR columns are sparse (NULL off their dates) with recency columns carrying the gap.

```
spine = cross_join(reservoirs, daily_ist_calendar)
```

### 5.2 Timezone normalisation (FR-ABT-2)

The **canonical key is the IST calendar date** (contract Conventions).
- **Bulletins:** already IST → take the calendar date directly.
- **SAR `Observation.acquisition_date`:** RS emits it already mapped to the IST date (contract §1) — trust it; do not re-shift.
- **Forcing (ERA5-Land/IMERG/CHIRPS/GLDAS/MODIS) and GFS:** native UTC. Convert each UTC timestamp to `Asia/Kolkata` (UTC+5:30), then take the IST calendar date *before* the daily reduction, so a UTC day's tail that crosses midnight IST lands on the correct IST day.

### 5.3 As-of (point-in-time) joins — no leakage (FR-ABT-3)

Every column on row `date` holds only what was knowable at `date`.

1. **Ground truth → spine.** Left-join bulletins on exact IST date. Populate `gt_level`, `gt_live_storage_bcm`, `gt_pct_filled`, `normal_storage_pct`; static `frl`, `live_capacity_bcm` from registry (non-null every row). `days_since_bulletin` = days since the most-recent **past-or-equal** bulletin (backward-looking only — never the next bulletin).
2. **Satellite-derived → spine.** Left-join `Observation` on IST acquisition date. Populate `surface_area`, `area_confidence`, `derived_volume`, `derived_level`, `extraction_method`. `days_since_acquisition` = days since most-recent past-or-equal acquisition.
3. **Catchment forcing → spine.** Left-join `CatchmentForcing` on `(reservoir_id, date)`. These are native-daily and *observed* (point-in-time valid by construction — reanalysis has a few-days lag, captured in `freshness_flags`, but each value belongs to its own valid date, not a future revision).
4. **Forecast forcing** is **not** joined into the wide ABT (contract v2). It lives in `ForecastForcing` keyed `(reservoir_id, issue_date, horizon)`; ML joins it on `issue_date = date`. DE just ensures each `issue_date` row is built from the GFS run issued **≤ issue_date** at valid time `issue_date + horizon` (the point-in-time rule that prevents reanalysis leak and gives train/serve consistency vs reforecasts, §8.2).

**Asof rule:** all recency/as-of operations use `merge_asof(direction='backward')` on the IST date — the single mechanism that guarantees no future row contributes to a past row.

### 5.4 Nearest-match fusion within tolerance (FR-ABT-2, FR-DE-3, FR-GT-1)

`GroundTruthMatch` pairs each bulletin with its nearest acquisition (which may be future *or* past — this is a *calibration* artifact, not a serving feature, so symmetric nearest is allowed here) within `±N` days; pairs exceeding tolerance are rejected and the gap recorded. This table is the rating-curve fitting input (ML) and the residual source — it is **distinct from** the leakage-safe ABT spine join (which is strictly backward).

### 5.5 Resampling higher-cadence forcing (FR-ABT-2)

- IMERG 30-min, GLDAS 3-hourly, GFS 4×/day → reduce to daily IST (sum for precip/melt, mean for SWE/T2m, fraction for SCA) inside the `xee`/`xarray` reduction before the join.
- Engineered: `antecedent_precip_index` = exponentially-decayed sum of catchment precip (configurable half-life capturing routing delay); `degree_day_melt` = `max(0, T2m − T_base)` × melt-factor; `snow_cover_area` trend = rolling slope of SCA.

### 5.6 Bootstrap / two-pass (closed-loop, ADR-0004/0005)

`Observation.derived_volume/level` are NULL until a rating curve exists, and the curve is fit (ML) from `GroundTruthMatch`. Sequence:
1. **Pass 1:** DE builds ABT with `derived_*` NULL (or from stub inversion); emits `GroundTruthMatch` (area ↔ bulletin pairs).
2. ML fits the blended rating curve (FR-GT-4) from those pairs.
3. **Pass 2:** RS re-emits `Observation` with `derived_*` populated; DE rebuilds ABT, computes `residual_vs_ground_truth` and `is_extrapolated` (derived value above observed fill max). New `abt_version`.

### 5.7 Quality, freshness, versioning (FR-ABT-4/5, FR-DE-4)

- `row_quality ∈ {ok, low_confidence, quarantine}` from gates: fill% ∈ [0,110], area ≥ 0, level ≤ FRL+tol, `area_confidence` threshold, forcing freshness.
- `freshness_flags` (jsonb): per-source staleness (e.g. ERA5-Land lag days, GFS run age, `days_since_acquisition`).
- `source_versions` (jsonb): dataset/model versions per source group.
- `abt_version`: monotonic snapshot tag (e.g. `abt-YYYYMMDD-<gitsha>-<contract_version>`), recorded in `load_audit` and surfaced to MLflow (AC-10).

### 5.8 Idempotent upsert (FR-DE-6)

`INSERT ... ON CONFLICT (reservoir_id, date) DO UPDATE` via the DB-team SQLAlchemy models (Postgres dialect upsert). Re-running a date range is safe (§4.3). Prefect `cache_key_fn` keyed on `(reservoir_id, date_range, source_versions)` skips redundant recompute.

---

## 6. Task breakdown (sequenced; T-01…)

| ID | Task | Depends on | Acceptance check |
| --- | --- | --- | --- |
| **T-01** | Scaffold `pipelines/data_engineering/` (uv project, pandera/GE/geemap/xee/prefect deps), `orchestration/` flow skeleton, GE context. | — | `uv sync` clean; `prefect` importable; empty `de_pipeline_flow` runs. |
| **T-02** | Promote `build_unified_dataset.py` cleaning into `de/cleaning.py` (canonical names, units, dedup). Bulletin **bronze→silver** (`ingest_bulletins`, `clean_bulletins`). | T-01 | Cleaned bulletins match existing unified CSV row-for-row; IST tz stamped. |
| **T-03** | **pandera + GE suites** for bulletins (schema/ranges/nulls/continuity); quarantine path + `quarantine` table; load/audit log. (FR-DE-2/4/6, NFR-TEST-1) | T-02 | Inject a bad row (fill 150%, negative level) → quarantined, run still green, audit row written. |
| **T-04** | `pull_observations` + **`fuse_observations_groundtruth`** → `GroundTruthMatch` (nearest ±N days, `time_gap_days`). Handle stubs. (FR-DE-3, FR-GT-1) | T-03 | Every bulletin paired or rejected-with-reason; gaps recorded; tolerance configurable. |
| **T-05** | `compute_residuals` on `GroundTruthMatch` (NULL-safe pre-curve). (FR-DE-5) | T-04 | Residual = derived−bulletin pct_filled when curve present; NULL otherwise; no crash pre-curve. |
| **T-06** | **`delineate_catchment`** — `pyflwdir` on MERIT `upa` from dam point, HydroBASINS scaffold, area validation, PostGIS persist + manual override. (FR-DE-7) | T-01 | 3 catchment polygons persisted; delineated area within tolerance of published basin areas; override config respected. |
| **T-07** | **`pull_hydromet_raw` + `aggregate_forcing`** → `CatchmentForcing` (ERA5-Land lead, IMERG/CHIRPS cross-check, MODIS SCA, GLDAS); antecedent index, degree-day melt, SCA trend; UTC→IST. (FR-DE-8/9/11) | T-06 | `CatchmentForcing` daily rows for all 3 reservoirs; precip/SWE/SCA non-negative; freshness flags populated. |
| **T-08** | **`build_forecast_forcing`** → `ForecastForcing` `(reservoir, issue_date, horizon)` from GFS incl. archived reforecasts; point-in-time run selection; forecast degree-day melt. (FR-DE-10) | T-06 | For a sampled past `issue_date`, features come only from runs ≤ issue_date; horizons 1–14 present. |
| **T-09** | `validate_forcing` pandera/GE on `CatchmentForcing` + `ForecastForcing`. (FR-DE-4, NFR-TEST-1) | T-07,T-08 | Out-of-range forcing quarantined; suite runs every flow. |
| **T-10** | **`build_abt`** — spine, tz normalise, backward as-of joins, quality/freshness/version flags. (FR-DE-12, FR-ABT-1..5) | T-05,T-09 | ABT matches contract §2 exactly (columns/types/units/grain); `(reservoir,date)` unique; static FRL/capacity non-null. |
| **T-11** | **`validate_abt`** GE checkpoint — schema, grain uniqueness, **point-in-time invariants** (no future leak), flag coverage; + `upsert_gold` idempotent + `abt_version`. (AC-10, FR-DE-6) | T-10 | Re-run produces identical rows (idempotent); leakage probe test fails build if a future value appears. |
| **T-12** | **Prefect deployments + trigger chain** — `de_pipeline_flow` (RS→DE entrypoint), `emit_ml_trigger` on success; retries/backoff, concurrency tags, observability (status/duration/row counts). (§4.3, NFR-REL-1/2) | T-11 | RS completion triggers DE; DE success triggers ML; failure alerts + retries observed. |
| **T-13** | **Regression backtest task** — end-to-end ABT build over a known near-FRL episode wired into CI. (AC-12, NFR-TEST-3) | T-11 | CI green on a frozen episode fixture; ABT row counts/flags stable. |
| **T-14** | Two-pass curve bootstrap wiring (Pass-2 residual/extrapolation backfill after ML fits curve). (§5.6, ADR-0004) | T-05,T-10 | Post-curve ABT rebuild fills `derived_*`, `residual_vs_ground_truth`, `is_extrapolated`; new `abt_version`. |

---

## 7. Interfaces / contracts exposed

### 7.1 ABT contract (to ML) — frozen, `contract_version: 2`

- **Grain:** one row per `(reservoir_id, date)`, **continuous daily IST calendar**. Sparse GT/SAR columns NULL off their dates; `days_since_bulletin` / `days_since_acquisition` carry recency. Forecaster trains on rows where a storage target exists.
- **Columns** (see contract §2 for exact types/units/nulls):
  - Keys/alignment: `reservoir_id`, `date`, `days_since_bulletin`, `days_since_acquisition`.
  - Ground truth: `gt_level` (m), `gt_live_storage_bcm` (BCM), `gt_pct_filled` (%), `frl` (m, non-null), `live_capacity_bcm` (non-null), `normal_storage_pct` (% rule-curve proxy, ADR-0002).
  - Satellite: `surface_area` (km²), `area_confidence` (0–1), `derived_volume` (BCM), `derived_level` (m), `extraction_method`.
  - Forcing: `catchment_precip` (mm/day), `antecedent_precip_index` (mm), `snow_cover_area` (0–1), `swe` (mm), `degree_day_melt` (mm/day).
  - Provenance/quality/target: `is_extrapolated` (bool), `residual_vs_ground_truth` (%), `source_versions` (jsonb), `freshness_flags` (jsonb), `row_quality` (`ok`/`low_confidence`/`quarantine`), `abt_version`.
- **Alignment policy:** IST canonical date; backward as-of for serving features (no leakage); symmetric nearest ±N only for the calibration `GroundTruthMatch` artifact.

### 7.2 `ForecastForcing` contract (to ML) — contract §3

Grain `(reservoir_id, issue_date, horizon 1–14)`; columns `forecast_precip` (mm/day), `forecast_degree_day_melt` (mm/day), `gfs_run_cycle` (timestamptz), `source_versions`. Built from GFS run ≤ `issue_date` at valid time `issue_date + horizon`. ML joins on `issue_date = date`.

### 7.3 Forcing-feature definitions (FR-DE-8/9/10/11)

| Feature | Definition | Source priority |
| --- | --- | --- |
| `catchment_precip` | catchment-mean daily precip | ERA5-Land → IMERG → CHIRPS |
| `antecedent_precip_index` | exp-decayed sum of recent catchment precip (configurable half-life) | derived |
| `snow_cover_area` | catchment snow fraction (NDSI threshold) + rolling trend | MODIS MOD10A1 |
| `swe` | catchment-mean snow water equivalent | ERA5-Land `snow_depth_water_equivalent` / GLDAS `SWE_inst` |
| `degree_day_melt` | `max(0, T2m − T_base) × melt_factor` | ERA5-Land `temperature_2m` / GLDAS |
| `forecast_precip` | catchment-mean GFS precip at valid time | GFS `total_precipitation_surface` |
| `forecast_degree_day_melt` | degree-day from GFS forecast T2m | GFS `temperature_2m_above_ground` |

### 7.4 Flow-trigger contract (§4.3)

- **Inbound:** RS pipeline calls DE on successful `Observation` emission (Prefect deployment run / event). DE flow params: `{reservoir_ids?, date_range?, force_rebuild?}`.
- **Outbound:** on `validate_abt` + `upsert_gold` success, DE triggers `ml_pipeline_flow` with `{abt_version}`. On failure, no downstream trigger; admin alert + retry/backoff (NFR-REL-1).
- **Idempotency:** upserts keyed `(reservoir_id, date)` (and `(reservoir, issue_date, horizon)` for forecast forcing) — safe re-run (§4.3).

---

## 8. Library choices

| Concern | Choice | Rationale |
| --- | --- | --- |
| Env/packaging | **`uv`** | mandated (NFR-MNT-1); reproducible lockfile. |
| Orchestration | **Prefect 2** | tasks/flows/deployments, retries+backoff, caching for idempotency, concurrency tags for GEE quota, observability (NFR-REL-1/2). |
| GEE access | **`geemap`** (server-side EE) + **`xee`** (EE→`xarray`) | mandated; thin/swappable per §4.4 — wrap behind a `de/gee_client.py` adapter so a Copernicus/openEO backend can replace it without touching transforms. |
| Catchment delineation | **`pyflwdir`** on MERIT `upa`, HydroBASINS scaffold | FR-DE-7; `geopandas`/`shapely` for polygon ops, `PostGIS` persist. |
| DataFrames | **pandas** (+ `xarray` for raster reduction) | bulletins are small (~583 rows); pandas `merge_asof` is the point-in-time engine. |
| Validation | **pandera** (typed in-pipeline schemas) + **Great Expectations** (suite/checkpoint, docs) | NFR-TEST-1; pandera for fast inline gates, GE for the auditable ABT checkpoint in CI. |
| DB | **PostgreSQL + PostGIS** via DB-team **SQLAlchemy** models | mandated; upsert via Postgres `ON CONFLICT`. |
| Geometry | `geopandas`, `shapely` | catchment/AOI ops. |
| Testing | `pytest` | unit (transforms, tz, as-of) + integration (E2E backtest, NFR-TEST-2/3). |

---

## 9. Testing / data-validation strategy (NFR-TEST-1/2/3, §7.8)

- **Per-run validation (every flow):** pandera schemas inline at each silver/gold boundary; GE checkpoint on the ABT. Failing rows → `quarantine.*`, never propagated (NFR-TEST-1). Checks: schema/types, ranges (fill% 0–110, area≥0, level≤FRL+tol, SWE/SCA/precip≥0), nulls (static FRL/capacity non-null), temporal continuity (no gaps in daily spine), cross-field consistency (derived vs bulletin within tolerance flag).
- **Point-in-time / leakage probe (CI gate, AC-10/AC-12):** a deterministic test that injects a sentinel "future" value and asserts it never appears on an earlier ABT row; asserts every as-of join is `direction='backward'`.
- **Unit tests (NFR-TEST-2):** tz mapping (UTC midnight crossing IST), `merge_asof` recency, antecedent-index decay, degree-day melt, dedup precedence, idempotent upsert (re-run → identical rows).
- **Integration / E2E backtest (NFR-TEST-3, AC-12):** build the full ABT over a frozen near-FRL episode fixture; assert row counts, flags, and a stable `abt_version` schema. Wired into **CI** (AC-12).
- **Idempotency test:** run `de_pipeline_flow` twice over the same range → zero net row change, audit log shows upsert.

---

## 10. Risks & open decisions

| # | Risk / open question | Disposition |
| --- | --- | --- |
| R1 | **Bootstrap circularity** — `derived_*` need a rating curve; curve needs `GroundTruthMatch`. | Resolved by two-pass build (§5.6) + stub `Observation` rule. Confirm Pass-2 re-trigger ownership with RS/ML. |
| R2 | **Tolerance `±N` days** for nearest-match (FR-GT-1) not numerically fixed. | **Open — affects ML/GT.** Propose ±N configurable, default per revisit (~6–12d). Needs sign-off from ground-truthing (plan 03/05). |
| R3 | **Transboundary catchment** (Sutlej into Tibet) — forcing coverage + GEE clip extent. | Delineate full upstream area regardless of border; flag coverage in `freshness_flags`. Validate area vs published. |
| R4 | **GFS archive depth** — reforecasts back to 2015 assumed (contract v2). | Verify `NOAA/GFS0P25` archive truly covers 2015-07 at build time; if gaps, fall back to "model the observed→forecast gap" (§8.2). **Affects ML train/serve consistency.** |
| R5 | **GEE quota / latency** for 11y × 5 datasets × 3 catchments. | Prefect concurrency tag + caching + scheduled batching (§10 risks, spec). Backoff/retry on EE errors. |
| R6 | **`normal_storage_pct` sparsity** — proxy populated only where bulletins carry it (ADR-0002). | NULL-safe; ML's mass-balance recession handles NULL. Document coverage. |
| R7 | **Contract change discipline** — any ABT column change bumps `contract_version` + notifies RS/ML (ADR-0003). | DE must not silently alter the schema; CI asserts ABT == contract. |
| R8 | **Closed loop (ADR-0005)** — bulletins end 2026-04; production runs SAR+forcing only. | ABT spine extends past last bulletin with NULL GT + `days_since_bulletin` growing; ML uses SAR-derived state. No live GT re-validation. |

---

## 11. Mapping to acceptance criteria

| AC | How this plan satisfies it |
| --- | --- |
| **AC-1** (all pipelines run end-to-end automatically, no manual steps) | T-12 Prefect deployments + RS→DE→ML trigger chain; idempotent, observable, retried (§4.3, §4 flow design). DE owns the DE link and the ML trigger. |
| **AC-10** (ABT built, point-in-time correct, versioned, the dataset all models use) | §5 ABT algorithm (backward as-of, leakage probe), `abt_version` snapshots to MLflow, T-10/T-11; ABT is ML's sole input (§3). Frozen contract §2. |
| **AC-12** (automated data-validation + regression backtest pass in CI) | §9 pandera+GE on every run, leakage probe, E2E near-FRL backtest fixture (T-13); all wired into CI. |
