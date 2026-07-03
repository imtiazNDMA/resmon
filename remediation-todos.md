# Remediation TODOs — from the 2026-07-03 six-agent critical review

Source: consolidated review at commit `3a639b2` (RS science, ML, data engineering, backend, frontend, claims-audit). Tracks are file-disjoint so they can be worked in parallel. Severity: 🔴 critical · 🟠 high · 🟡 medium.

## Track A — Data integrity (`pipelines/data_engineering/`, `orchestration/`)

- [x] 🔴 A1 Stub upsert guard: `stub_observations.py` `ON CONFLICT ... DO UPDATE` must only update rows `WHERE observation.extraction_method = 'stub'` — never overwrite real SAR rows
- [x] 🔴 A2 Pipeline ordering: `run_full_pipeline` must rebuild the ABT **after** the RS pipeline writes real observations (DE → RS → fusion → ABT → ML)
- [x] 🟠 A3 Converging upserts: `build_abt.py` / `ingest.py` / `forcing.py` / `seed.py` `DO UPDATE` clauses must refresh **all** payload columns so reruns converge to source of truth
- [x] 🟠 A4 Apply ERA5 publication latency (5 days, already recorded in `source_versions`) when joining `catchment_forcing` into the ABT — information-set time, not event time
- [x] 🟠 A5 Run pandera validation (`validate_bulletins`, `validate_abt`) inside `run_de_pipeline`, not only in tests; resolve the `pct_filled > 110` low_confidence vs `ABT_SCHEMA` [0,110] contradiction
- [x] 🟡 A6 Unit bombs: convert ERA5 `temperature_2m` K→°C before degree-day melt; precip m→mm per contract
- [x] 🟡 A7 Contract "never a silent zero": missing forcing → NULL, not 0.0 (incl. `evaporation`, `snow_cover_area`, `swe`)
- [x] 🟡 A8 Write `pipeline_run` rows (start/end/status per stage) from `run_full_pipeline`
- [x] 🟡 A9 Fusion: exclude stub observations from `ground_truth_match` (they match their own source — circular)
- [x] 🟡 A10 Make stub generation conditional (skip when real observations exist / flag-controlled)

## Track B — Remote sensing science (`pipelines/remote_sensing/`, `pipelines/_common/`, `scripts/populate_geometry.py`)

- [x] 🔴 B1 `gee_real.py`: replace the fixed −18 dB threshold with per-scene adaptive thresholding (server-side `ee.Reducer.histogram` → client-side Otsu on the histogram, through the extractor registry semantics)
- [x] 🔴 B2 `gee_real.py`: enforce `orbit_relative`/`pass_direction` filters from reservoir config; reject scenes that do not fully cover the AOI (`filterBounds` = intersects, not covers)
- [x] 🔴 B3 `gee_real.py`: never coerce failed reduction to 0 km² (`area_m2 or 0.0`) — raise / return None and skip the write
- [x] 🔴 B4 Catchment: HydroBASINS upstream traversal (`HYBAS_ID`/`NEXT_DOWN` union), not the single level-7 basin containing the dam; sanity-check vs published drainage areas (Bhakra ≈ 56,900 km²)
- [x] 🟠 B5 AOI: use GSW `max_extent` (or occurrence ≥ ~5%), dam-connected component, drop the 12 km point-buffer clip; reconcile the 25% vs 50% occurrence inconsistency
- [x] 🟠 B6 Extractors: NaN/masked-pixel handling; bimodality/abstain gate (no confident water on unimodal scenes); wire `mask_border_noise` into the pipeline (currently dead code)
- [x] 🟠 B7 Unify the separability statistic across otsu/kmeans/gmm (same metric, same scale) so `area_confidence` is comparable
- [x] 🟡 B8 Area reduction: pin `crs`, reduce at native 10 m, drop `bestEffort` (or log effective scale into `processing_params`)
- [x] 🟡 B9 Honest confidence in `populate_geometry.py`: no hardcoded `area_confidence=0.8` / `layover_shadow_fraction=0.0`; register `extraction_method` strings in the extractor registry
- [x] 🟡 B10 Adversarial extractor tests: realistic speckle (gamma ENL≈4.5), 5 dB separation, wind-merged modes, dry-pool unimodal (must abstain), <5% water fraction, NaN borders
- [ ] ⏳ Deferred (needs GEE/DEM execution): γ⁰ terrain flattening, layover/shadow masks, DEM hypsometry, frozen orbit numbers

## Track C — ML statistics (`pipelines/ml/`)

- [x] 🔴 C1 Replace the tautological AC-5 backtest: replay the forecaster at historical base dates, run `assess_release_risk` on those forecasts, score hits/misses/false alarms/lead against observed episodes (delete hard-coded `fired: True`)
- [x] 🔴 C2 `release_probability`: make coherent — consistent input (point vs upper bound), finite-sample conformal quantile, and either calibrate against replayed episodes or relabel as an ordinal risk index in the schema/API
- [x] 🟠 C3 Conformal: `ceil((n+1)(1−α))/n` quantile, per-horizon halfwidths, add a PICP coverage test
- [x] 🟠 C4 Real walk-forward CV (expanding window) with `MAX_HORIZON`-day purge between train/cal/test; per-horizon + per-reservoir skill breakout
- [x] 🟠 C5 Stamp gate results with data provenance: `on_synthetic: true` when observations carry `scene_ids=['synthetic']` (AC-2/AC-3/AC-5 must carry the caveat into their persisted results)
- [x] 🟡 C6 Horizon mismatch: don't serve horizons the model never trained on (weekly bulletins → only 7/14-day gaps); interpolate or restrict served horizons honestly
- [x] 🟡 C7 `release.py`: don't collapse NULL `interval_high` to the point forecast; don't assume contiguous horizons from row order
- [x] 🟡 C8 Episode detection: handle plateaus (sustained 100% fill), tie thresholds to per-reservoir config
- [ ] ⏳ Deferred (needs real forcing): inflow features in `FEATURES`, ABT as the training source, AC-4 skill claim

## Track D — Backend serving & security (`api/`, `core/`, `db/`, `infra/`)

- [x] 🔴 D1 Caddyfile: remove public `/mlflow/*` and `/prefect/*` routes (admin planes must not be internet-reachable unauthenticated)
- [x] 🔴 D2 Compose: move the Postgres host-port publish out of the base file into the dev override; parameterize `app_rw`/`app_ro`/`mlflow` passwords via env (no defaults in `01-init.sql`)
- [x] 🔴 D3 Fix `/health/ready` engine leak: reuse a cached engine instead of `make_engine()` per request
- [x] 🟠 D4 Bound the public query surface: `ST_SimplifyPreserveTopology` + `maxdecimaldigits` on all `/geojson/*`; `statement_timeout` for `app_ro`; explicit pool sizing/timeouts in `make_engine`
- [x] 🟠 D5 Typed `response_model` on every route (shapes already exist in `repositories.py`) — kills the hand-rolled Decimal coercion class of bugs
- [x] 🟠 D6 Fix `abt_current` view: latest version by `created_at`, not lexicographic text sort (breaks at `abt_v10`) — new migration
- [x] 🟠 D7 Fix `db/migrations/env.py` include_object: PostGIS tiger tables reflect with `schema=None` — filter by table name too (this is what broke CI)
- [x] 🟡 D8 `root_path="/api"` on the FastAPI app so `/api/docs` works behind Caddy
- [x] 🟡 D9 Staleness clock: `data_age_days` from IST (`Asia/Kolkata`), not server-local `date.today()`
- [x] 🟡 D10 Append-only hardening: `BEFORE TRUNCATE` statement trigger on `prediction`/`release_risk`
- [x] 🟡 D11 Separate databases (or schemas) for MLflow/Prefect so `alembic check` stays truthful against the deployed stack

## Track E — CI & repo hygiene (`.github/`, repo root, `docs/`)

- [x] 🔴 E1 Promote `Replan.md.tmp.25376.d8b893092159` → `docs/plans/08-replan-proposal-pinn.md` (clearly marked PROPOSAL, not adopted) and remove the tmp file
- [x] 🟠 E2 CI: add a web job (npm ci, tsc, vite build); bump deprecated action versions
- [ ] 🟠 E3 Verify CI goes green end-to-end once D7 lands (the only historical run failed at `alembic check`)
- [x] 🟡 E4 README: update the stale "Phase 0" status line; note the remediation effort
- [x] 🟡 E5 Remove the `main.py` "Hello" scaffold stub (verify nothing references it first)
- [x] 🟡 E6 Document that `geeservice.json` should live outside the repo per the `/run/secrets` convention (don't move it without coordinating local setup)

## Track F — Frontend (`web/`)

- [x] 🔴 F1 Stale-response race: AbortController/generation counter on the per-reservoir effect; clear `series`/`forecast` (not just `status`) on switch
- [x] 🔴 F2 Per-layer degradation: `Promise.allSettled` on initial load — risk markers must never be hostage to a GEE overlay; per-source error scoping, cleared on success, with retry
- [x] 🟠 F3 Refresh: polling (~90 s) + refetch-on-focus for status/fleet-risk/series
- [x] 🟠 F4 Risk semantics: grey "unknown" badge (never Low-blue for null); dark text on the Watch badge (WCAG); fix "Data d old" null interpolation
- [x] 🟠 F5 Forecast axis: allow > 110% (never clip the overtopping scenario) + `ReferenceLine` at 100/FRL
- [x] 🟡 F6 `GeoJSON` components: `key` prop tied to data identity so overlays update on refresh
- [x] 🟡 F7 Type the GeoJSON `properties` (`WaterExtentProperties` etc.) instead of `as`-laundering
- [x] 🟡 F8 Build hygiene: `npm ci` (no `|| npm install` fallback), Node LTS base image

## Cross-cutting decisions still open

- [ ] **PINN vs blended rating curve** (the tmp replan proposal) — settle before investing further in Track B/C curve work
- [ ] Live GEE execution pass (unblocks the ⏳ deferred items in B and C)
