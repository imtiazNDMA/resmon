# Unified Reservoir Dataset — Design Spec

**Date:** 2026-06-16
**Status:** Approved (brainstorming)
**Owner:** Data Engineering pipeline (FR-DE-1, FR-DE-2; see `requirements.md` §5.2, §6.2)

---

## 1. Goal

Produce a single, uniform, weekly reservoir ground-truth time series in `data/db/`,
conforming exactly to the §6.2 ground-truth schema, by cleaning and merging the raw
files in `data/to_be_cleaned/` with the already-clean 2025 historical file.

This is the bronze→silver→gold cleaning step that feeds the rest of the platform.

## 2. Output

- **File:** `data/db/reservoir_unified_weekly.csv`
- **Grain:** one row per `(reservoir, ISO week)`
- **Span:** 2015–2025
- **Reservoirs:** GOBIND SAGAR, PONG DAM, THEIN DAM
- **Schema (exact §6.2 column order, matching `data/historical/reservoir_timeseries.csv`):**
  `SR. NO.`, `RESERVOIR NAME`, `FRL (M)`, `CURRENT RESERVOIR LEVEL (M)`,
  `LIVE CAPACITY AT FRL (BCM)`, `CURRENT LIVE STORAGE (BCM)`, `DATE`,
  `STORAGE AS % OF LIVE CAPACITY AT FRL - CURRENT YEAR`,
  `STORAGE AS % OF LIVE CAPACITY AT FRL - LAST YEAR`,
  `STORAGE AS % OF LIVE CAPACITY AT FRL - NORMAL STORAGE`,
  `BENEFITS - IRR-CCA`, `BENEFITS - HYDEL IN MW`, `SOURCE_PDF`, `pct_filled`

## 3. Sources

| Source file | Cadence | Span | Units | source_tag |
| --- | --- | --- | --- | --- |
| `historical/reservoir_timeseries.csv` | weekly | 2025 | m, BCM | `historical_2025` |
| `to_be_cleaned/Indian Dams Storage Level(2).xlsx - Sheet1.csv` | weekly | 2024 | ft, MAF | `csv_2024` |
| `to_be_cleaned/Indian_Dams_Data-2020_2024.xlsx` (sheet `MAIN`) | daily | 2020–24 | ft, MAF | `daily_sitrep` |
| `to_be_cleaned/Weekly … Eastern Rivers … (2015-2024).xlsx` (sheets Bhakra/Pong/Thein) | weekly | 2015–24 | ft, MAF | `cwc_weekly` |

**Ignored:**
- `_$Indian Dams Storage Level-2024 year.xlsx` — Excel owner-lock file, not data.
- `Indian_Dams_Data-2020_2024.xlsx` sheets `BHAKRA_clean`, `PONG` — deduped subsets of `MAIN`; using them would double-count.
- `precipitation_2020_24` sheet — catchment forcing, different grain; excluded per scope decision.

## 4. Conversions (empirically validated against the 2025 historical file)

- `FT_TO_M = 0.3048` — Bhakra 1680 ft = 512.06 m vs historical 512.00 ✓
- `MAF_TO_BCM = 1.233481838` — 5.05 MAF = 6.229 BCM vs historical 6.229 ✓
- Cross-checked for all three reservoirs on FRL and live capacity.

## 5. Canonical reservoir registry

Alias → identity, plus static metadata backfilled into every row (sourced from the
2025 historical file). Live capacity treated as constant (sedimentation ignored at this stage).

| Canonical | Aliases | FRL (M) | Capacity (BCM) | IRR-CCA | HYDEL MW |
| --- | --- | --- | --- | --- | --- |
| GOBIND SAGAR | Bhakra, "Bhakra Dam on River Sutlej" | 512.00 | 6.229 | 676 | 1379 |
| PONG DAM | Pong, "Pong Dam on River Beas" | 423.67 | 6.157 | 0 | 396 |
| THEIN DAM | Thein, "Thein Dam on River Ravi" | 527.91 | 2.344 | 348 | 600 |

## 6. Pipeline stages

1. **Read + normalize** each source to intermediate frame
   `(reservoir, date, level_m, storage_bcm, last_year_pct, source_tag, source_pdf)`.
   - `csv_2024`: ft→m, MAF→BCM; forward-fill sparse `Dated`; parse `d/m/yyyy`.
   - `daily_sitrep`: ft→m, MAF→BCM; parse `Date of SITREP`.
   - `cwc_weekly`: strip title rows on Pong/Thein sheets; multi-format date parse (ISO + `dd.mm.yyyy`); ft→m, MAF→BCM.
   - `historical_2025`: already schema/units; carries real benefits + normal/last-year %.
2. **Resample daily → weekly:** for `daily_sitrep`, key on ISO `(year, week)`, keep the **last observation per reservoir-week**.
3. **Dedup across sources** by `(reservoir, ISO year-week)`, precedence
   `historical_2025 > cwc_weekly > daily_sitrep > csv_2024`.
4. **Backfill static fields** (FRL, capacity, benefits) from the registry — overrides any bad source value (e.g. daily MAIN's wrong Pong FRL 1421 ft → corrected to 423.67 m).
5. **Compute** `pct_filled = storage_bcm / capacity_bcm × 100`; `CURRENT YEAR %` = `pct_filled`;
   `last year %` from source where present, else blank; `normal %` blank except historical.
6. **Quality gates:** drop rows missing both level and storage; flag/clamp `pct_filled`
   outside 0–110; reject negatives. Quarantined rows logged (count + reason).
7. **Assemble** exact §6.2 columns; regenerate `SR. NO.` per date group; sort by `DATE`
   then reservoir; `SOURCE_PDF` = originating filename for non-2025 rows; write CSV.

## 7. Non-goals

- No extra signal columns (inflow / outflow / precipitation dropped).
- No separate precipitation/catchment-forcing file.
- No retention of daily granularity (intentionally collapsed to weekly).

## 8. Validation

- Row counts per source and post-dedup logged.
- Spot-check: converted FRL/capacity per reservoir equal the registry values.
- `pct_filled` recomputed equals source `Storage %` within rounding tolerance.
