# Frontend Overhaul — Reservoir Analytics Analyst Console

**Date:** 2026-06-30 · **Status:** Approved design (pre-plan) · **Topic:** Complete frontend/UI/UX remake

## Problem & goal

The current dashboard (`web/`, ~600 LOC, plain CSS, monolithic `App.tsx`) is a thin
two-pane map + side-panel. We are replacing it with an **analyst deep-dive console**: a
modern, information-rich, map-centric workspace whose centerpiece is a **left control
sidebar** (reservoir controls, layer/imagery toggles, before/after comparison) and a
**bottom acquisition timeline** spanning every SAR acquisition collected to the most
recent date.

Primary user: **technical analyst** exploring SAR-derived storage, forecasts, and model
accuracy — optimize for density, charts, tables, imagery comparison, and downloadable
series.

## Decisions made during brainstorming

| # | Decision |
| --- | --- |
| B1 | **Imagery data gap → build now, synth masks.** Only 1 real water-mask polygon per reservoir exists (latest GEE pull); ~193 other observations have area/fill numbers but no mask. We build the full imagery UX now; dates lacking a real mask get a **derived** polygon (the real mask scaled about its centroid to that date's measured area), flagged `derived: true`. Swaps to real masks later with **zero UI change**. |
| B2 | **Styling foundation → Tailwind CSS + shadcn/ui** (Radix primitives). Matches plan decision D12. |
| B3 | **Primary user → analyst / deep-dive.** Dense charts, data tables, before/after imagery analysis, downloadable series, lots of detail visible. |
| B4 | **Layout → EO-browser canvas.** Topbar · left control sidebar · full-bleed map canvas (with before/after swipe) · collapsible right analytics drawer · bottom scrubbable acquisition timeline. |

## Non-goals

- No change to ML / forecast / release-risk internals, the frozen contracts, or the
  pipeline. This is frontend + two small **read-only** API endpoints.
- No auth / RBAC / alerting (descoped for v1, unchanged).
- Not running historical GEE extraction here (that remains the separate, documented gap;
  this design is explicitly built to absorb it later without UI changes).

## Architecture

### Layout shell (four regions, dark analyst theme)

```
┌──────────────────────────────────────────────────────────┐
│ TOPBAR  brand · fleet risk chips · freshness · search       │
├──────────┬──────────────────────────────┬─────────────────┤
│ CONTROL  │        MAP CANVAS             │  ANALYTICS      │
│ SIDEBAR  │   (before│after swipe)        │  DRAWER  ◀▶     │
│          │     markers · overlays        │  KPIs/charts    │
├──────────┴──────────────────────────────┴─────────────────┤
│ ACQUISITION TIMELINE  (~194 dates, area sparkline, scrub)   │
└──────────────────────────────────────────────────────────┘
```

- **Topbar** — brand; fleet risk chips (click → select reservoir); global data-freshness
  indicator (14-day threshold, D8); reservoir search/select.
- **Left Control Sidebar** (collapsible): reservoir selector; **layer toggles** (AOI / SAR
  water / catchment / markers); **imagery controls** (single-date vs before/after mode +
  two date pickers); derived-mask notice.
- **Center Map Canvas** — full-bleed Leaflet; Esri satellite + OSM street base layers;
  risk-coloured `CircleMarker`s; water-extent overlay for the **active date**;
  **before/after swipe slider** on the map when compare mode is on.
- **Right Analytics Drawer** (collapsible): KPI grid, trend chart, forecast+risk, accuracy.
- **Bottom Acquisition Timeline** — scrubbable filmstrip of all acquisitions to latest,
  with an area sparkline; scrubbing sets the active date; two dates can be pinned to the
  before/after comparison.

### Cross-cutting UI state — Zustand store

A single small store keeps the four regions in sync without prop-drilling:

```ts
interface UiState {
  selectedReservoir: string | null;
  activeDate: string | null;            // drives the map water overlay + KPIs context
  compareMode: boolean;
  compare: { before: string | null; after: string | null };
  layers: { aoi: boolean; water: boolean; catchment: boolean; markers: boolean };
  sidebarOpen: boolean;
  drawerOpen: boolean;
}
```

### Server state — TanStack Query

All fetching goes through typed query hooks (caching, loading, error). Per-date
water-extent fetches are cached by `(reservoirId, date)` so timeline scrubbing and
before/after re-use are instant after first load.

### Backend additions (read-only; synthesis lives server-side)

1. `GET /reservoirs/{id}/acquisitions`
   → `[{ date, surface_area_km2, pct_filled, has_real_mask }]` — ordered ascending.
   Drives the bottom timeline and the date pickers.

2. `GET /reservoirs/{id}/water-extent?date=YYYY-MM-DD`
   → GeoJSON Feature for that date's water polygon.
   - If a real mask exists for that observation → return it (`derived: false`).
   - Else → take the reservoir's single real mask and scale it about its centroid by
     `factor = sqrt(target_area / source_area)` (PostGIS `ST_Scale` around centroid) to
     match that date's measured `surface_area`; return with `derived: true`.
   - The existing `/geojson/water-extent` (latest-per-reservoir) stays for the markers/
     default overlay.

Both endpoints are pure reads, contract-additive (no `contract_version` bump — these are
serving views, not pipeline contracts), and tested via the existing TestClient + `get_db`
override pattern.

### Component structure (replaces monolithic `App.tsx`)

```
web/src/
  main.tsx
  App.tsx                 # layout shell only: topbar + sidebar + map + drawer + timeline
  index.css               # tailwind directives + dark-theme tokens
  types.ts                # extended with Acquisition + WaterExtentFeature
  lib/
    api.ts                # typed fetch client (+ acquisitions, waterExtentByDate)
    queries.ts            # TanStack Query hooks
    store.ts              # Zustand UI store
    format.ts             # defensive numeric coercion (fx)
    risk.ts               # RISK_COLOR + labels
  components/
    layout/  TopBar · ControlSidebar · AnalyticsDrawer · AcquisitionTimeline
    map/     MapCanvas · ReservoirMarkers · WaterExtentLayer · BeforeAfterSwipe · LayerToggles
    panels/  KpiGrid · TrendChart · ForecastChart · ReleaseRiskPanel · AccuracyPanel · DataTable
    ui/      # shadcn primitives (button, card, slider, tabs, tooltip, switch, badge, dialog, scroll-area)
```

Each unit has one purpose and a typed interface; the Zustand store is the only shared
mutable state.

## Feature detail

### Imagery / before-after (the named requests)
- **Single-date mode:** the active date (from the timeline scrubber or a picker) sets the
  water overlay on the map. A **"derived"** badge shows whenever the displayed mask is
  synthetic.
- **Before/after mode:** pin two dates; the map shows a vertical **swipe slider** — left of
  the handle renders the "before" water overlay, right renders "after" — with a
  date+area label on each side and a delta (Δ km², Δ fill %) readout.
- **Acquisition timeline:** horizontal filmstrip of all ~194 dates with an area sparkline;
  click to set active date, shift/alt-click (or two pin buttons) to set before/after.

### Analyst panels (right drawer)
- **KpiGrid:** fill %, level vs FRL, storage BCM, surface area km², release prob + lead,
  data age/staleness.
- **TrendChart:** fill vs seasonal normal; toggle storage/level; brush-to-zoom.
- **ForecastChart:** 1–14 day predicted line + conformal interval band; optional baseline
  overlay.
- **ReleaseRiskPanel:** level, probability, lead time, **contributing factors**
  (explainable, transparent layer — ADR-0001).
- **AccuracyPanel:** historical-backtest framing, explicitly labelled (ADR-0005).
- **DataTable:** the active timeseries with a **CSV download**.

## Error handling & honesty states

- Loading **skeletons** per panel; empty + error states (typed, surfaced, not swallowed).
- **Staleness banner** when `data_age_days > 14` (D8) — serving last-known forecast-based
  risk.
- Always-visible **"derived imagery"** badge whenever a non-real mask is shown, so
  synthetic geometry is never mistaken for real SAR extraction (honesty per ADR-0005).
- Numeric fields coerced defensively (Postgres `numeric` may arrive as string).

## Testing & verification

- `npm run build` (`tsc --noEmit && vite build`) clean — the existing CI-equivalent gate.
- New API endpoints: pytest via TestClient + `get_db` override (no commits), incl. the
  derived-scaling path (`derived: true`, area within tolerance of target).
- Propose adding **Vitest + React Testing Library** to `web/` in the plan for the store +
  a couple of component smoke tests (not a blocker for the redesign).
- Live smoke pass: bring up the stack, scrub the timeline, run a before/after swipe, toggle
  layers, download a CSV, confirm staleness + derived badges render.

## Risks & notes

- **Derived masks are size-honest, shape-borrowed.** The badge + the `derived` flag make
  this explicit; the seam (server-side synthesis behind a stable contract) means real
  masks drop in later with no frontend change — the single most important design property.
- New frontend deps (Tailwind, shadcn/ui, TanStack Query, Zustand) expand the lean stack
  the project deliberately chose; justified by B2/B3 (analyst-grade, cohesive UI) and
  isolated to `web/`.
- Two new endpoints touch `api/` only (read-only, additive); no DB migration, no contract
  bump.
