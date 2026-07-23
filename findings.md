# Comprehensive Codebase Review — Findings & Fixes

> Generated 2026-07-16 from parallel specialized reviews of 6 domains.
> Total findings: ~130 across remote-sensing, data-engineering, database, ML, frontend, and backend.

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Remote Sensing (SAR Water Extraction)](#1-remote-sensing-sar-water-extraction)
3. [Data Engineering Pipeline](#2-data-engineering-pipeline)
4. [Database Schema & ORM](#3-database-schema--orm)
5. [ML & Modeling (Forecasting, Episodes, Release Risk)](#4-ml--modeling)
6. [Frontend (React/TypeScript Dashboard)](#5-frontend)
7. [Backend API (FastAPI)](#6-backend-api)
8. [Cross-Cutting Concerns](#7-cross-cutting-concerns)
9. [Priority Action Items](#8-priority-action-items)

---

## Executive Summary

The codebase is structurally coherent (monorepo, ADRs, pipelined architecture) but contains **systematic issues** that undermine correctness and production readiness:

- **Critical**: Hardcoded `100 m²` pixel area for Sentinel-1 — introduces 9–24% bias in all area measurements. Empty catchment polygon in `forcing.py` poisons all ERA5 climate data. Forecast forcing is hardcoded zeros. No FK indexes on most tables.
- **High**: GEE initialized on every tile request (API), `area_confidence` uncalibrated, no pagination on any API endpoint, no rating-curve uncertainty propagation, silent data loss in backfill, substring alias matching in cleaning.
- **Systemic**: ~0 logging across all Python pipelines, no loading/error/empty states in the frontend, no thread-safety in DB session factory, no relationship() directives in ORM.

### Remediation Started

The following items have been addressed in the first pass:

- `forcing.py`: catchment forcing now loads persisted `catchment_geom` for real backends and refuses empty production regions.
- `forcing.py` / `pipeline.py`: forecast forcing no longer writes fake zero-valued GFS rows.
- `forcing.py`: missing data bands now raise instead of silently substituting the first variable.
- `area.py`: `surface_area_km2` now requires explicit per-pixel area; no hidden 100 m² Sentinel-1 default remains.
- `area.py`: vector compactness now computes local projection latitude per ring.
- `remote_sensing/pipeline.py`: synthetic framework rows now stamp explicit processing provenance in JSON.
- `gee_tiles.py`: Earth Engine initialization and key parsing are cached; tile cache is bounded.
- `config.py` / `session.py`: DB URLs no longer default to working credentials; missing URLs fail fast.
- `SarTileLayer.tsx`: interrupted Leaflet tile crossfades clean up stale layers and guard opacity updates.
- DB schema: added Alembic migration `9f1a2b3c4d5e` with FK query indexes for rating curves, predictions, release risk, and pipeline runs.
- `release.py`: release-risk now anchors to the saved prediction trajectory, so newer bulletins cannot filter out valid forecast horizons.
- `curve.py`: empirical rating curves now reject non-positive capacity, non-finite training rows, duplicate area values, and flag both lower/upper extrapolation.
- Frontend state/query layer: initial view-swap no longer fights app-load animation, markers/rainfall/status have stale times, layer toggles use updater state, and timeline stale-date handling is explicit.
- API: SAR tile `date` query parameter is FastAPI-validated as an ISO date; tile cache eviction has test coverage.
- DB schema: added Alembic migration `a2b4c6d8e0f1` with a database-level `reservoir.updated_at` trigger for raw SQL updates.

---

## 1. Remote Sensing (SAR Water Extraction)

### CRITICAL

**1.1 `area.py:14` — Sentinel-1 pixel area constant is systematically wrong**
```python
S1_PIXEL_AREA_M2 = 100.0  # 10 m × 10 m
```
Sentinel-1 IW incidence angle spans 23°–36.5°. Ground-projected pixel area at near range: 100/cos(23°) ≈ 109 m²; at far range: 100/cos(36.5°) ≈ 124 m². Using 100 m² is a **9–24% systematic bias** in all backfill-derived areas. The GEE path in `gee_real.py` correctly uses `ee.Image.pixelArea()`.
**Fix**: Remove the default from `pixel_area_m2` parameter. Require the caller to provide the actual projected pixel area per scene.

**1.2 `backfill.py:222-251` — Scenes silently dropped when GEE returns fewer results than requested**
`_chunk_histograms` iterates over whatever GEE returns, NOT over the input `ids` list. If GEE drops scenes (computation timeout, server-side filtering), they simply vanish. The driver's `done_scene_ids` marks ids from `list_scene_ids` as done, not from results. A dropped scene is **permanently lost** — never retried.
**Fix**: Diff returned result IDs against input IDs. Log and record missing IDs as `"error"` with detail `"scene dropped by GEE server"`.

**1.3 `backfill_extraction.py:36-40` + `backfill.py:256-262` — Transient GEE errors permanently skip scenes**
When `_chunk_areas` returns null for a scene, it's recorded as `status="error"` and the scene ID enters `done_scene_ids`. A transient GEE error (quota exceeded, network blip) permanently loses the observation.
**Fix**: Separate "permanent error" from "retryable error". Write a separate failed-ids file that's consulted but not treated as done.

**1.4 `gee_real.py:110` — `simplify(300).buffer(250)` is a band-aid over broken GEE vectorization**
The comment admits `reduceToVectors` emits self-intersecting rings that crash later GEE calls. The simplify+buffer workaround can itself produce invalid geometries for complex shorelines. No `isValid()` check.
**Fix**: Add `ee.Geometry.isValid()` check. Fall back to a conservative bounding-box buffer around the dam point if vectorization produces invalid geometry.

### HIGH

**1.5 `area.py:88-96` — `area_confidence` is uncalibrated, exponents are arbitrary**
```python
sep**0.5 * comp**0.25 * layover_ok**0.25
```
No empirical or physical basis for these exponents or the multiplicative form. Stored in the DB and used downstream as if validated. The `layover_ok` term is always 1.0 because `populate_geometry.py:53` records `layover_shadow_fraction=0`.
**Fix**: Calibrate against known-truth masks, or remove confidence until validated. At minimum, document "this is an uncalibrated heuristic".

**1.6 `aoi.py:115-119` — `polygon_to_wkt` emits invalid WKT**
```python
return f"MULTIPOLYGON((({coords})))"
```
Missing space between `MULTIPOLYGON` and `(((`. PostGIS `ST_GeomFromText` will reject this.
**Fix**: `f"MULTIPOLYGON ((({coords})))"`.

**1.7 `gee_real.py:67-80` — `init_ee` retries `FileNotFoundError` 4 times with backoff**
tenacity catches the exception (not a `GeeExtractionError`), retries 3 more times with exponential delays — each retry wastes time.
**Fix**: Catch `FileNotFoundError` before the retry decorator.

**1.8 `backfill.py:106` — `ee.Filter.contains` without `maxError` is an approximate spatial predicate**
GEE's `contains` filter uses a simplified geometry for `.geo`. Complex AOI polygons may cause false negatives/positives.
**Fix**: Add `maxError` to the filter, or use `filterBounds` + client-side verification.

### MEDIUM

**1.9 `area.py:55-66` — `_ring_area_perimeter_m` applies lat0 from first ring only for MultiPolygon**
Rings at different latitudes use the lat0 of the first ring. For reservoirs spanning >0.5° latitude, distortion grows.
**Fix**: Compute lat0 per ring.

**1.10 `extractors.py:178,181` vs `gee_real.py:278,280` — Array path and GEE path compute separability differently**
`OtsuVH.extract()` uses `fisher_separability()` on raw values; `gee_real.py` uses `fisher_from_histogram()` on histogram bins. For small N (<1000 pixels), they can differ → different abstain decisions.
**Fix**: Use the same computation in both paths.

**1.11 `pipeline.py:46-61` — `synth_scene` uses additive Gaussian noise in dB (physically incorrect)**
SAR speckle is multiplicative in linear power, not additive in dB. The correct model uses gamma-distributed noise on linear power.
**Fix**: Model speckle as gamma noise on linear backscatter, then convert to dB.

**1.12 `calibrate.py:18` — Fixed −30 dB floor for all reservoirs and bands**
S1 IW NESZ varies from −22 dB (far range) to −26 dB (near range). A fixed floor clips valid data or passes noise.
**Fix**: Make floor a function of incidence angle or use S1 noise LUT.

**1.13 `aoi.py:77,94-95` — Fixed angular buffer `buffer_deg=0.01` varies in linear size with latitude**
At 31°N ≈ 1.1 km; at 60°N ≈ 0.55 km.
**Fix**: Specify buffer in meters, convert to degrees at scene latitude.

**1.14 `scene_inventory.py:158` — `by_orbit.index[0]` crashes if no scenes cover the AOI**
If all scenes have `covers=False`, selecting `by_orbit.index[0]` produces an empty result and downstream `best["date"]` fails.
**Fix**: Check `by_orbit` is non-empty.

---

## 2. Data Engineering Pipeline

### CRITICAL

**2.1 `forcing.py:116` — Catchment polygon never populated → garbage ERA5 forcing**
```python
region: dict = {}  # real path: the persisted catchment polygon GeoJSON
```
`region` is initialized to an empty dict and **never assigned a real value**. `aggregate_forcing` passes this to `backend.get_collection(...)`, which in production (GEE) will spatially average ERA5-Land over no polygon or a default extent. Every downstream model is silently poisoned with meaningless precipitation/temperature values.
**Fix**: Wire in the persisted catchment polygon lookup from `reservoir.catchment_geom`, or raise a hard error if region is empty.

**2.2 `forcing.py:174-175` — Forecast forcing is hardcoded zeros**
```python
"forecast_precip": 0.0,
"forecast_degree_day_melt": 0.0,
```
`build_forecast_forcing` writes literal zeros for every horizon. No FIXME, TODO, or assertion. The ML pipeline trains on these zeros and learns to ignore forecast forcing entirely.
**Fix**: Raise `NotImplementedError("forecast forcing not wired")` and stub the function at the orchestration level, or insert a sentinel value (NULL).

**2.3 `forcing.py:76-77` — Silent band-name fallback substitutes wrong data**
```python
else:  # fall back to the first var
    da = next(iter(ds.data_vars.values()))
```
If `band not in ds.data_vars`, the code silently substitutes the wrong physical variable.
**Fix**: Raise `KeyError(f"Band {band!r} not found in dataset; available: {list(ds.data_vars)}")`.

**2.4 `cleaning.py:24-33` — Substring alias match captures unintended names**
```python
if alias in text: return name
```
`"thein"` matches "THEIN DAM" but also "THEIN DAM FOREBAY" or "LOWER THEIN". Latent correctness bomb when fleet expands.
**Fix**: Require word-boundary match: `re.search(rf'\b{re.escape(alias)}\b', text, re.I)`.

### HIGH

**2.5 `pipeline.py:83-85` — Only 2 forecast issue dates produced**
```python
issue_dates = [d for d in (forcing_start, forcing_end)]
```
Exactly 2 issue dates, each with 14 horizons = 28 rows of zeros per reservoir. Not a seed — a stub that populates the table with plausible-looking garbage.
**Fix**: Remove `build_forecast_forcing` from the main pipeline, or raise `NotImplementedError`.

**2.6 `dataaccess.py:195` — Default backend "gee" raises `NotImplementedError` on `get_collection`**
```python
key = (name or os.environ.get("DATA_ACCESS_BACKEND") or "gee").lower()
```
Production runs that don't set `DATA_ACCESS_BACKEND=fixture` crash on the first `aggregate_forcing` call.
**Fix**: Switch default to "fixture" until GEE is wired, or make `get_backend()` raise a hard error.

**2.7 `build_abt.py:167` — `fillna("ok")` hides unverified rows**
ABT rows without ground-truth bulletins are silently labeled `"ok"`. Downstream cannot distinguish "verified by bulletin" from "no bulletin exists".
**Fix**: Use `"unverified"` as fill value, or keep NULL and make schema accept NULL.

**2.8 `session.py:39-40` — Global session factory not thread-safe**
```python
_rw_factory: sessionmaker[Session] | None = None
```
Two threads calling `_factory()` concurrently can both see `None`, both create factories, one leaks.
**Fix**: Use `lru_cache` or a `threading.Lock`.

### MEDIUM

**2.9 `stub_observations.py:28` — Stub area formula is unitless and uncalibrated**
```sql
100.0 * power(GREATEST(COALESCE(gt.pct_filled, 0), 0) / 100.0, 0.7)
```
A unitless number stored as `surface_area`. No calibration to actual reservoir geometry.
**Fix**: Compute reservoir-specific area from FRL geometry, or document the expected physical range.

**2.10 All DE files — Zero logging**
The entire DE pipeline has no logging. When a step fails, you get a raw traceback with no context about which reservoir or SQL query was running.
**Fix**: Add INFO logging per reservoir with row counts and elapsed time. Add ERROR context on every exception path.

**2.11 `cleaning.py:92-96` — ISO week dedup is silent**
When multiple bulletins arrive in the same ISO week, the latest is kept and the rest are silently dropped. No counter, no log.
**Fix**: Log the count of deduplicated rows. Consider quarantining conflicts.

**2.12 `build_abt.py:113` — `NoResultFound` crashes with no context**
`.one()` raises `sqlalchemy.exc.NoResultFound` if reservoir_id doesn't exist — no message about which reservoir was missing.
**Fix**: Catch and re-raise with `f"Reservoir {reservoir_id!r} not found"`.

**2.13 `forcing.py:176` — Hardcoded GFS run cycle timestamp**
```python
"gfs_run_cycle": f"{issue.isoformat()}T00:00:00+00:00",
```
Hardcodes 00:00 UTC. Real GFS has 4 runs/day (00/06/12/18).
**Fix**: Remove `gfs_run_cycle` from stub, or make it NULL.

**2.14 `seed.py:35` — Fragile `aoi_version` string comparison**
Guard against clobbering real AOI depends on exactly matching `'placeholder_v0'`. Any pipeline setting `aoi_version` to something else (even `'placeholder_v1'`) silently clobbers.
**Fix**: Use a boolean `is_placeholder` column or `aoi_version IS NULL` sentinel.

---

## 3. Database Schema & ORM

### CRITICAL

**3.1 Missing FK indexes — sequential scans on every join**
The following FK columns have zero index support:
| Table | FK Column | Referenced Table |
|---|---|---|
| `rating_curve` | `reservoir_id` | `reservoir` |
| `prediction` | `model_version_id` | `model_version` |
| `release_risk` | `model_version_id` | `model_version` |
| `pipeline_run` | `reservoir_id` | `reservoir` |
"`rating_curve.reservoir_id`" is accessed on every release-risk display request — full table scan.
**Fix**: Add indexes: `idx_<table>_<column>` on every FK column.

**3.2 `cb96ab2f3b5e` migration — NOT NULL columns added without defaults**
Lines 299–341 add `dam_point`, `aoi_geom`, `aoi_version`, `release_thresholds` — all `NOT NULL`, most without `server_default`. If `reservoir` has any row, the migration crashes.
**Fix**: Add column with default, then `ALTER COLUMN SET NOT NULL`.

**3.3 `reservoir.py:48-49` — `updated_at` is ORM-only, not enforced at DB level**
`onupdate=func.now()` fires only when SQLAlchemy issues the UPDATE. A raw SQL `UPDATE reservoir SET ...` silently skips it.
**Fix**: Add `BEFORE UPDATE` trigger: `NEW.updated_at = now()`.

**3.4 `abt.py:40` — TEXT PK breaks lexicographic sorting at v10+**
PK `(reservoir_id, date, abt_version)` uses `Text`. `abt_v9 > abt_v10` lexicographically.
**Fix**: Pad versions (`abt_v001`) or use Integer version column. The `abt_current` view workaround (migration 7c4e9a1d2b6f) only fixes the view, not the PK B-tree.

**3.5 No partitioning or retention on time-series tables**
`analytical_base_table`, `prediction`, `release_risk` have no partitioning and no retention policy. Append-only tables accumulate forever.
**Fix**: Add range partitioning on `date`/`run_timestamp`. Add a retention job for `prediction` and `release_risk`.

### HIGH

**3.6 No optimistic locking for concurrent pipeline runs**
Zero models have a `version` column or optimistic lock. The partial unique index `uq_rating_curve_one_active` prevents two active curves, but "deactivate old → activate new" is not transactional.
**Fix**: Use `SELECT ... FOR UPDATE` before flipping active curves, or add `xmin`/`version` column.

**3.7 No `relationship()` directives — N+1 by design**
No ORM `relationship()` defined on any model. Every join must be explicit. No cascade, no eager loading.
**Fix**: Add minimal `relationship()` with `lazy='selectin'` on FK targets that are always joined.

**3.8 No `ST_IsValid` constraints on geometry columns**
`dam_point`, `aoi_geom`, `catchment_geom`, `water_mask_geom` have no spatial validity enforcement. A pipeline bug can insert `MULTIPOLYGON EMPTY`.
**Fix**: Add `CheckConstraint("ST_IsValid(aoi_geom)")` and similar for all geometry columns.

**3.9 `pipeline_run.reservoir_id` is nullable with ambiguous semantics**
Nullable `reservoir_id` with no `scope` column to disambiguate "global" vs "per-reservoir" runs. No index on this join key.
**Fix**: Either make NOT NULL or add a `scope` column.

**3.10 Only 4 of 14 models have Pydantic schemas**
Missing schemas for: `GroundTruth`, `GroundTruthMatch`, `RatingCurve`, `Reservoir`, `CatchmentForcing`, `Prediction`, `ReleaseRisk`, `PipelineRun`, `ModelVersion`, `ReservoirCapacityHistory`.
**Fix**: Add `Upsert` schemas for every input table.

### MEDIUM

**3.11 `ground_truth.py:31-32` — `Numeric` with no precision/scale**
`benefits_irr_cca` and `benefits_hydel_mw` use `Numeric()` with no precision or scale.
**Fix**: `Numeric(12, 2)` or whatever the bulletin precision is.

**3.12 No DESC index for "latest X" queries**
PK is `(reservoir_id, acquisition_date)` ASC. "Get latest" queries scan backwards. A DESC index would be more efficient.
**Fix**: `CREATE INDEX idx_obs_res_date_desc ON observation(reservoir_id, acquisition_date DESC)`.

**3.13 `env.py:21-37` — `include_object` doesn't filter PostGIS functions**
PostGIS functions/operators appearing in autogenerate could trigger DROP statements.
**Fix**: Filter `type_ == "function"` returning False.

**3.14 No cascade policy on FKs**
Deleting a `reservoir` leaves orphan rows in every child table. No `ON DELETE CASCADE` or `SET NULL`.
**Fix**: Document "no cascade" policy explicitly, or add cascade to dependent tables like `ground_truth_match`.

**3.15 `session.py:47,50` — `expire_on_commit=False` enables stale reads**
Objects in session cache won't auto-refresh after commit. Long-lived sessions serve stale data.
**Fix**: Set `expire_on_commit=True` and add `populate_existing` where needed.

**3.16 `env.py` — alembic env does not pass `compare_type=True` consistently**
While `compare_type=True` is set in both online and offline mode, the `render_item` function from `geoalchemy2` may not handle all type comparisons correctly (e.g., `Numeric` with vs without precision).
**Fix**: Review and pin the geoalchemy2 version. Add integration tests for autogenerate correctness.

---

## 4. ML & Modeling

### CRITICAL

**4.1 `release.py:52-68` — Horizon date / base date mismatch silences release risk**
`base_date` is read from the **latest ground truth** row, but predictions were generated from an earlier base date. If a bulletin arrives between forecast run and risk run, `horizon_date - new_base < 1` filters all predictions, producing zero risk assessments silently.
**Fix**: Store `base_date` in the `prediction` table, or run release risk sequentially after forecasting in the same transaction.

### HIGH

**4.2 `curve.py:25-29` / `estimation.py:55-63` — No rating-curve uncertainty propagation**
`RatingCurveFit` returns point estimates with no standard error or prediction interval. The entire conformal layer covers forecast uncertainty only — ignoring rating-curve uncertainty, which can be dominant for reservoirs with few (area, bulletin) pairs.
**Fix**: Return a bootstrap prediction interval or the residual standard error. The estimation bridge should output `(storage, storage_std)`.

### MEDIUM

**4.3 `curve.py:34-35` — `is_extrapolated` only checks upper bound**
```python
def is_extrapolated(self, area) -> bool:
    return area > self.observed_range["area_max"]
```
Areas below `area_min` can produce negative storage/level via `polyval` — never flagged.
**Fix**: Add `or area < self.observed_range["area_min"]`.

**4.4 `forecaster.py:65` / `forecasting.py:74` / `episodes.py:169` — `np.log(cap)` produces `-inf` / NaN**
`live_capacity_bcm` from DB passed directly to `np.log()`. NULL, zero, or negative capacity produces `-inf` or NaN, silently degrading predictions.
**Fix**: Add `cap = max(cap, 1e-6)` before log. Add DB CHECK constraint `live_capacity_bcm > 0`.

**4.5 `episodes.py:129` — Negative index when `cal_frac > train_frac`**
```python
cal_start = dates[int(len(dates) * (train_frac - cal_frac))]
```
If `cal_frac > train_frac`, `train_frac - cal_frac` is negative → `dates[-1]` (last date!) → data leak.
**Fix**: Clamp: `max(0, int(len(dates) * (train_frac - cal_frac)))`.

**4.6 `episodes.py:228` — False alarms justified by pre-cutoff episodes**
The false-alarm loop iterates over `all_episodes` including those with onset before cutoff. Alerts just after cutoff can be "justified" by pre-cutoff episodes, undercounting false alarms.
**Fix**: Use `eval_episodes` (post-cutoff only) for false-alarm check.

**4.7 `groundtruthing.py:167` — Capacity pinned to first row's value**
```python
cap = float(df["live_capacity_bcm"].iloc[0])
```
Assumes all rows share the same capacity. If capacity varies (sedimentation corrections), fill-% is computed against an arbitrary value.
**Fix**: Use an explicit `reservoir.capacity_bcm` column or `df["live_capacity_bcm"].median()` with warning if values differ.

**4.8 `forecasting.py:99-100` — Walk-forward fold split by row-count, not by time**
`np.array_split` splits by row-count. Unevenly spaced bulletins cause folds with different time spans — per-fold metrics incomparable.
**Fix**: Split by percentile of date range: `bounds = np.linspace(eval_dates[0], eval_dates[-1], n_folds + 1)`.

**4.9 `forecaster.py:24` — Pooled model has no reservoir-ID feature**
`FEATURES` contains only `log_capacity` as reservoir-specific signal. Two reservoirs with similar capacity but different inflow regimes (snowmelt vs monsoon) are indistinguishable.
**Fix**: Add per-reservoir intercept or categorical embedding. Document maximum tolerable heterogeneity.

### LOW

**4.10 `episodes.py:58` — Peak at series start (index 0) never detected**
Loop starts at `i = 1`. A near-FRL peak at the first data point is missed. Unlikely but possible.
**Fix**: Start at `i = 0` with `pct[-1]` treated as below near-FRL.

**4.11 `forecaster.py:86` — `np.quantile(method='higher')` requires NumPy ≥1.22**
Older NumPy versions silently ignore the `method` keyword, breaking conformal coverage guarantee.
**Fix**: Add compatible fallback using manual sort + ceiling index.

**4.12 `forecaster.py:53` — `norm_j` fallback uses base fill instead of target fill**
```python
norm_j = normal[j] if not np.isnan(normal[j]) else pct[i]
```
When `normal_storage_pct` is NaN, falls back to the base fill `pct[i]`. The climatology baseline collapses to persistence (delta=0).
**Fix**: Use `pct[j]` (target observed fill) or drop examples with NaN normal values.

**4.13 `curve.py:52` — `areas.size` doesn't detect duplicate area values**
`areas.size` counts total pairs, not unique area values. With degree-2 polyfit and duplicate areas, `np.polyfit` silently produces NaN coefficients.
**Fix**: Check `np.unique(areas).size >= degree + 1`.

**4.14 `release_risk.py:116-117` — Redundant guard (dead code for standard intervals)**
The `if lead is None: prob = min(prob, 0.5)` guard is documented as a consistency check but is mathematically redundant for symmetric conformal intervals.
**Fix**: Remove or document as defence-in-depth with a note about its redundancy.

---

## 5. Frontend

### CRITICAL

**5.1 `SarTileLayer.tsx:15-41` — GSAP tween cleanup leaks Leaflet TileLayer on every date scrub**
The `prev` layer is only removed in the tween's `onComplete`. If effect cleanup fires mid-tween, `tween.kill()` stops the animation but `prev` is never removed from the map. Every rapid date change leaks a TileLayer.
**Fix**: In cleanup, also remove `prev`: `if (currentRef.current && map.hasLayer(currentRef.current)) map.removeLayer(currentRef.current)`.

**5.2 `SarTileLayer.tsx:22-30` — `onUpdate` fires after layer is removed, throws at `next.setOpacity`**
When effect cleanup removes `next` from the map, the in-flight tween's `onUpdate` tries `next.setOpacity()` on a destroyed layer → runtime error.
**Fix**: Guard with `if (!map.hasLayer(next)) { tween.kill(); return; }`.

### HIGH

**5.3 `MapView.tsx:64-67` — `activeDate` set cascades into competing GSAP re-animation**
On mount, `useEffect` calls `setActiveDate(acqs[last].date)` → store update → `App.tsx` re-renders → `viewSwap` fires again, re-animating the stage opacity/scale while `appLoadIn` is still running.
**Fix**: Let `TimelineDock` default to the last index locally. Only run `viewSwap` on actual view changes (compare previous/next in effect guard).

**5.4 `App.tsx:26` — `viewSwap` and `appLoadIn` fight over `.stage` opacity simultaneously**
`appLoadIn` animates `.stage` opacity 0 → 1 (0.9s). `viewSwap` animates `.stage` opacity 0.25 → 1 (0.45s). Both run on mount, fighting the same CSS property.
**Fix**: Skip `viewSwap` on initial mount, or make it target the child view element directly.

**5.5 `MapView.tsx:14-38` — `invalidateSize` may fire while container has zero dimensions**
`MapSizeInvalidator` runs while GSAP `viewSwap` applies `scale: 1.02` and `opacity: 0.25`. Leaflet may read `clientWidth === 0` → blank tiles.
**Fix**: Defer `invalidateSize` until after GSAP load-in completes (e.g., via `viewSwap`'s `onComplete` or a 1s delay from mount).

**5.6 `MapView.tsx:45-53` — `CameraDriver` re-fly on every `markers` refetch**
`useMarkers()` has no `staleTime` (default 0), so every component remount or focus refetch gives a new `markers` reference, calling `map.flyTo()`.
**Fix**: Add `staleTime: 10 * 60_000` to `useMarkers`, or only fly on `selected` changes.

**5.7 `store.ts:36-39` — `toggleLayer` uses `get()` for stale reads instead of updater pattern**
Two rapid toggles in the same synchronous batch read the same old value, making the second a no-op.
**Fix**: Use updater form: `set((state) => ({ showCatchment: !state.showCatchment }))`.

**5.8 `TimelineDock.tsx:21-24` — `activeDate` not found in acquisitions snaps to index 0 silently**
If `activeDate` is stale, `findIndex` returns -1, `Math.max(0, -1)` returns 0. Slider snaps to first acquisition with no visual indication.
**Fix**: Return -1 and handle it in the range input to show "—" instead.

### MEDIUM

**5.9 `api.ts:25-29` — No timeout, no response validation on API calls**
`fetch` calls can hang indefinitely. Response shape cast with `as T` — zero runtime validation.
**Fix**: Add `AbortSignal.timeout(15000)`. Consider zod validation on critical responses.

**5.10 `queries.ts:49-54` — `useRainfall` has `staleTime=0`, refetches on every mount**
Combined with StrictMode double-mount, two network requests fire on mount.
**Fix**: Add `staleTime: 10 * 60_000`.

**5.11 `DashboardView.tsx:29` — Rainfall hardcoded to Gobind Sagar**
```tsx
const { data: rainfall } = useRainfall("gobind_sagar");
```
Always shows Gobind Sagar rainfall, not the selected reservoir.
**Fix**: Use selected reservoir from store, or aggregate across fleet.

**5.12 `DashboardView.tsx:40-54` — Fleet merge recalculated on every render**
`byDate` Map and `fleet` array computed in render body without `useMemo`.
**Fix**: Wrap in `useMemo`.

**5.13 `AreaMeter.tsx:28-40` — Infinite GSAP shimmer tween causes continuous layout**
`repeat: -1` sine animation on `backgroundPosition` triggers continuous style recalculation for component lifetime.
**Fix**: Use CSS `@keyframes` instead of JS-driven GSAP for simple shimmer.

**5.14 `ReservoirButton.tsx:33-36` — No error/loading state distinction**
Sub-text shows `"—%"` for both loading and error states. User can't tell if loading or API is down.
**Fix**: Show spinner during loading, error indicator on failure.

**5.15 `MapView.tsx:87-98` — Coordinates destructured without bounds check**
```tsx
const [lon, lat] = f.geometry.coordinates;
```
`lat` can be `undefined` for malformed GeoJSON. Passed to Leaflet as `undefined`.
**Fix**: Validate `coordinates.length >= 2` and `lat != null`.

**5.16 `motion.ts:24-25` — `parseFloat("—")` returns NaN, masked by `|| 0`**
```ts
const obj = { v: parseFloat(el.textContent ?? "0") || 0 };
```
Works by accident but is fragile.
**Fix**: Check for `"—"` explicitly and start from 0.

### LOW

**5.17 `styles.css` — Multiple hardcoded colors instead of CSS variables**
Lines 21, 26, 29, 39 use hardcoded `#12314a`, `#0e1116`, `rgba(...)` instead of CSS custom properties.
**Fix**: Use `var(--panel-2)`, `var(--bg)`, `var(--water)` with opacity.

**5.18 `motion.ts:62-76` — `buttonSweep` creates DOM outside React, lost on re-render**
The `.sweep` div is appended via `el.appendChild`. React re-render replaces the DOM, leaving GSAP animating a detached node.
**Fix**: Render sweep div inside React JSX and toggle via state.

**5.19 `vite.config.ts:12` — Proxy rewrite may strip `/api` prefix**
```ts
rewrite: (p) => p.replace(/^\/api/, ""),
```
If backend routes are mounted at `/api`, the rewrite breaks all requests by stripping the prefix.
**Fix**: Confirm backend expects no prefix, or remove rewrite.

**5.20 `index.html` — Missing meta description, favicon, `<noscript>` tag**
For a deployed monitoring app, missing SEO metadata and JS-disabled fallback.
**Fix**: Add standard HTML meta tags.

---

## 6. Backend API

### CRITICAL

**6.1 `gee_tiles.py:36-39` — GEE initialized on every tile mint — massive performance waste**
`ee.Initialize()` is called inside `mint_tile()` on every cache miss. Each initialization does network I/O. Under load or with many `(rid, date)` keys, this serializes init calls.
**Fix**: Initialize EE once at module level via a lazy singleton. Cache parsed credentials.

**6.2 `gee_tiles.py:17,58` — In-memory cache with no eviction — memory leak**
`_CACHE` is a plain `dict` that grows forever. Every unique `(rid, date)` pair adds an entry. Malicious client can exhaust memory.
**Fix**: Use `functools.lru_cache(maxsize=256)` or add eviction check before insert.

**6.3 `config.py:28-33` — Default database credentials in source code**
```python
database_url_rw: str = Field(default="postgresql+psycopg://app_rw:app_rw@localhost:5432/reservoir")
```
Production credentials as defaults. A deploy that forgets to override exposes the DB.
**Fix**: Remove defaults — force env-provided URLs. Use non-functional default like `"postgresql+psycopg://"`.

### HIGH

**6.4 `repositories.py:37,89,207,227,297` — SQL injection vector via f-string SQL fragments**
`_REAL_OBS` is injected into SQL via f-strings (`f"... WHERE {_REAL_OBS}"`). While currently a constant, this pattern is fragile. `_bounded_geojson()` (line 256) injects the same way.
**Fix**: Use SQLAlchemy `text()` with `and_()` / `or_()` for composable conditions.

**6.5 `gee_tiles.py:31` — `gee_sa_key_file` silently falls back to hardcoded filename**
```python
key_file = get_settings().gee_sa_key_file or "geeservice.json"
```
If not configured, silently uses `geeservice.json` from CWD. Confusing in production.
**Fix**: Fail explicitly with clear message when setting is not configured.

**6.6 No pagination on any list endpoint — unbounded result sets**
`list_reservoirs`, `reservoir_acquisitions`, `reservoir_rainfall`, `accuracy`, and all GeoJSON endpoints return all rows with no limit.
**Fix**: Add `limit` and `offset` query parameters to all list endpoints.

**6.7 `routes.py:85` — `date` parameter is unvalidated string**
```python
def reservoir_sar_tiles(rid: str, date: str, ...):
```
A malformed date hits the DB and potentially 500s.
**Fix**: Use `date: datetime.date` and let FastAPI validate.

### MEDIUM

**6.8 `routes.py:39-42,80,87,105` — N+1 existence checks for sub-resource endpoints**
`_ensure_reservoir()` does a separate `SELECT` for every sub-resource endpoint. Every endpoint pays an extra round trip.
**Fix**: Remove `_ensure_reservoir()` calls; let the data query return empty naturally.

**6.9 `repositories.py:131-149` — Latest forecast does two queries where one suffices**
First query gets `max(run_timestamp)`, second fetches rows. Single subquery/CTE would suffice.
**Fix**: Use `WHERE run_timestamp = (SELECT max(run_timestamp) FROM prediction WHERE ...)`.

**6.10 `gee_tiles.py:31-35` — Key file read and JSON-parse on every mint**
Even with singleton init, the key file is read and parsed on every cache miss.
**Fix**: Cache parsed credentials alongside the init flag.

**6.11 `gee_tiles.py:17` — Cache ineffective with multiple workers**
In-process dict cache is per-worker. Each uvicorn worker pays full cost for new dates.
**Fix**: Document per-worker caching tradeoff, or use shared Redis backend.

**6.12 `repositories.py:97` — `datetime.now(_IST)` evaluated per request**
Non-deterministic — makes tests time-dependent.
**Fix**: Accept optional `now` parameter defaulting to `None` (injectable).

**6.13 `repositories.py:173-177` — `accuracy` endpoint fetches all rating curves unbounded**
Returns all active rating curves with `fit_metrics` (potentially large JSON). No pagination.
**Fix**: Add limit/summarization.

### LOW

**6.14 No CORS middleware configured**
`main.py` has no `CORSMiddleware`. If Caddy proxy handles CORS, this is intentional but undocumented.
**Fix**: Add CORS middleware or document the proxy assumption.

**6.15 `main.py` — `session_scope` catches `SystemExit`, `KeyboardInterrupt`**
```python
except Exception:
    session.rollback()
```
Catch is too broad.
**Fix**: Use `except BaseException` or be more specific.

**6.16 `test_api.py:42` — Hardcoded reservoir count (`len(r.json()) == 3`)**
Fragile when seed data changes.
**Fix**: Assert `>= 1` or use reservoir-specific lookup.

---

## 7. Cross-Cutting Concerns

### 7.1 Zero structured logging across all Python pipelines
Not a single `log.info(...)`, `log.warning(...)`, or `print()` call exists in any pipeline file. Failures produce raw tracebacks with no context.

### 7.2 No loading/error/empty states in frontend
Every component renders data as if API calls always succeed. No loading skeletons, error banners, or empty-state placeholders.

### 7.3 Thread-safety in DB session factory
`core/src/core/db/session.py:39` has a data race on `_rw_factory` / `_ro_factory`. Two threads can both create factories.

### 7.4 No test coverage for the estimation bridge
The entire `area → storage/level` estimation bridge (`curve.py`, `estimation.py`) has no dedicated unit tests. The confidence in what the platform calls its "sole production path" has zero test coverage.

### 7.5 Rating-curve uncertainty invisible to downstream
Every consumer of derived_volume/derived_level treats it as ground truth. There is no error propagation from curve fitting → storage → fill% → feature → forecast → risk.

### 7.6 No sentinel values for "not yet implemented"
The codebase has several stubs that produce plausible-looking data instead of failing loudly:
- Forecast forcing → zeros
- Catchment forcing → empty region → garbage
- `layover_shadow_fraction` → 0.0 → inflated confidence

Each of these is a correctness bomb that will silently poison downstream consumers until someone remembers it exists.

---

## 8. Priority Action Items

### Immediate (fix before next deployment)

| # | Domain | File | Summary |
|---|--------|------|---------|
| 1 | Remote Sensing | `area.py:14` | Fix systematic 9-24% pixel area bias |
| 2 | Data Engineering | `forcing.py:116` | Wire real catchment polygon, stop garbage ERA5 |
| 3 | Data Engineering | `forcing.py:174-175` | Stop producing zero-valued forecast forcing |
| 4 | Backend | `gee_tiles.py:36-39` | Singleton GEE init, cache credentials |
| 5 | Frontend | `SarTileLayer.tsx:15-41` | Fix TileLayer leak on date scrub |
| 6 | ML | `release.py:52-68` | Fix base date mismatch silencing release risk |
| 7 | Database | All FK columns | Add missing FK indexes |
| 8 | Database | `cb96ab2f3b5e` migration | Fix NOT NULL columns w/o defaults |

### High Priority

| # | Domain | File | Summary |
|---|--------|------|---------|
| 9 | Backend | `repositories.py` | Replace f-string SQL injection patterns |
| 10 | Backend | `config.py:28-33` | Remove default DB credentials |
| 11 | ML | `curve.py/estimation.py` | Add rating-curve uncertainty propagation |
| 12 | Frontend | `App.tsx:26` | Fix competing GSAP animations on mount |
| 13 | Frontend | `store.ts:36-39` | Fix toggleLayer updater pattern |
| 14 | API | All list endpoints | Add pagination |
| 15 | Remote Sensing | `area.py:88-96` | Calibrate confidence or document as heuristic |
| 16 | Data Engineering | `cleaning.py:24-33` | Fix substring alias matching |
| 17 | Data Engineering | `seed.py:35` | Fix fragile aoi_version comparison |
| 18 | Database | `reservoir.py:48-49` | Add DB trigger for updated_at |

### Systemic

| # | Domain | Summary |
|---|--------|---------|
| 19 | All Python | Add structured logging with reservoir context |
| 20 | Frontend | Add loading, error, and empty states to every data view |
| 21 | Database | Add relationship() directives and cascade policy |
| 22 | All | Add sentinel values / guard assertions for unimplemented stubs |
| 23 | ML | Add dedicated tests for rating-curve estimation bridge |
| 24 | Deployment | Add CORS middleware or document proxy assumption |
| 25 | All | Add thread-safety to shared session factory |
