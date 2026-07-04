# Map Layers: Catchment + Water-Extent Overlays

**Date:** 2026-07-04
**Status:** Approved design, pending implementation plan
**Scope:** Sub-project A of the dashboard revamp (A: map layers, B: local SAR, C: real forcing, D: dashboard redesign)

## Goal

Render each reservoir's upstream catchment and latest SAR-derived water extent as
toggleable overlays on `MapView`, using the existing `/geojson/catchment` and
`/geojson/water-extent` endpoints. Delivers the "show basins" half of the dashboard
revamp feedback with data that already exists.

## Decisions (user-approved)

1. **Layer UX:** toggleable via a custom chips control, both layers default **on**.
2. **Catchment scope:** rendered for the **selected reservoir only** — the basin-wide
   home view stays clean; the catchment appears as part of the selection flow.
3. **Scrub conflict:** the water-extent polygon is from the single latest acquisition;
   it **auto-hides when the timeline is scrubbed to any earlier date** so the vector
   never contradicts the SAR raster underneath. It returns when the timeline is back
   on the latest acquisition.
4. **Staleness:** a date chip near the layer controls always shows the extent's
   acquisition date (`extent · 12 Jun`). If the acquisition is older than **14 days**,
   the chip turns amber and the polygon outline drops to ~50% opacity. The threshold
   mirrors `data_staleness_threshold_days` (default 14, `core/src/core/config.py`,
   NFR-REL-6/D8) as a frontend constant, and age is computed on the **IST calendar
   date** to match the backend's D9 convention (`Asia/Kolkata`, not the browser's
   local clock).
5. **Approach:** minimal, follow existing patterns. No layer-registry abstraction —
   sub-project B's open architecture decision (vector re-pass vs. cached rasters)
   would invalidate any abstraction designed now.

**Implementation deviations (deliberate, recorded at final review 2026-07-04):**
the date chip in decision 4 shows only while the water-extent toggle is on (a date
for a hidden layer is noise), and the auto-hide rule in decision 3 gates on the
*timeline's* latest acquisition rather than the mask's own date — the newest
backfill observations carry no masks, so strict equality against the mask date
would never be true. Both dissolve when sub-project B serves per-date masks.

## Architecture & data flow

Frontend fetch stack (all following existing patterns in `web/src/lib/`):

- `api.ts`: add `catchment()` and `waterExtent()` hitting `/geojson/catchment` and
  `/geojson/water-extent`. Both endpoints return all reservoirs (3 small features);
  fetched once, filtered client-side by `reservoir_id`. No new backend endpoints.
- `types.ts`: add `CatchmentProperties { reservoir_id, name, version }` and
  `WaterExtentProperties { reservoir_id, name, surface_area_km2, acquisition_date }`,
  mirroring the FastAPI response models in `api/src/api/routes.py`.
- `queries.ts`: add `useCatchment()` (`staleTime: Infinity`, geometry is static, same
  as `useAoi`) and `useWaterExtent()` (`staleTime: 10 min`, same as acquisitions).

## Components & state

- **`web/src/components/stage/CatchmentLayer.tsx`** — selected reservoir's catchment
  polygon via react-leaflet `GeoJSON`, keyed by `reservoir_id` for clean remounts on
  reservoir switch (same `key` trick as the AOI layer).
- **`web/src/components/stage/WaterExtentLayer.tsx`** — selected reservoir's latest
  mask polygon plus the date chip. Renders nothing when
  `isExtentVisible(activeDate, acquisition_date)` is false.
- **`web/src/components/stage/LayerChips.tsx`** — two toggle chips ("Catchment",
  "Water extent"), absolutely positioned top-right over the map (plain div, not a
  Leaflet control — same placement pattern as `AreaMeter`/`TimelineDock`). A chip
  renders dimmed/disabled when its layer has no data for the selected reservoir.
- **`web/src/lib/store.ts`** — `showCatchment: boolean` and `showWaterExtent: boolean`
  (both default `true`) + a `toggleLayer` action. Session-scoped; not persisted.
- **`web/src/lib/extentVisibility.ts`** —
  `isExtentVisible(activeDate: string | null, acquisitionDate: string): boolean`,
  pure function so the date-string comparison contract is unit-testable without
  mounting Leaflet. Also home to the staleness predicate.
- **`MapView.tsx`** — composes both layers; they render only when `selected !== null`
  and their store toggle is on.

## Styling

Distinguishable on dark satellite imagery; AOI unchanged:

| Layer | Color | Outline | Fill |
|---|---|---|---|
| AOI (existing) | `#59b7ff` | thin solid | 5% |
| Catchment | `#d9a45b` (sand) | dashed (`dashArray`) | ~4% |
| Water extent | `#39d5c8` (cyan) | solid | ~25% |

Stale extent (>14 days): outline opacity ~50%, chip amber.

## Error handling

Layers degrade independently — a failed catchment query must not affect the water
extent, the SAR tiles, or the base map (no `Promise.all` coupling, no sticky global
error). Query error or missing feature ⇒ that layer renders nothing, its chip dims.
React-query default retry covers transient failures.

## Backend scope rider: C5 provenance fix

`water_extent_features` in `api/src/api/repositories.py` currently filters only on
`water_mask_geom IS NOT NULL` — it lacks the `_REAL_OBS` filter, so a rerun of the
synthetic pipeline could serve a fake mask as "latest". Fix: append
`AND {_REAL_OBS}` to the WHERE clause. This is the C5 convention (see
`dev-db-synthetic-observation-mix` memory / commit f56b75e).

## Testing

- **vitest:** store toggle actions; `isExtentVisible` (equal dates, scrubbed back,
  null `activeDate`, format-mismatch guard); staleness predicate boundary (13/14/15 days).
- **pytest:** synthetic-provenance observation with a mask geometry is excluded from
  `water_extent_features` (same shape as the f56b75e serving-path tests).
- **Manual browser smoke:** chip toggles, reservoir switch, scrub-back auto-hide,
  stale tint (mock the clock or a fixture date).

## Out of scope

- Local SAR mask serving / historical extents per timeline date (sub-project B).
- Rain/snow/temp layers (sub-project C — current forcing data is synthetic).
- Persisting layer toggles across sessions.
- Zoom-dependent catchment visibility for all reservoirs at home zoom.
