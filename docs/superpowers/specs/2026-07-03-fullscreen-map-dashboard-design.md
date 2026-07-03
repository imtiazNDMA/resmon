# Fullscreen Map Dashboard — Frontend Redesign

**Date:** 2026-07-03 · **Status:** Approved design (pre-plan)
**Supersedes:** `2026-06-30-frontend-analyst-console-design.md` (clean-slate decision; that
spec's Tailwind/shadcn/EO-browser direction is retired — its per-date water-extent seam idea
survives here in evolved form as the acquisitions + SAR-tile endpoints).

## Problem & goal

Replace the current two-pane dashboard (`web/`) with a modern, fully-animated, map-first
console aligned with the Phase-1 rescope (`Replan.md`): state estimation is the product;
forecast/release-risk stay dormant. The new Stage-1.2 backfill (~280 real SAR acquisitions
per reservoir, 2015→present) becomes the visible heart of the UI: a scrubbable time series
of real Sentinel-1 imagery per reservoir.

## Decisions made during brainstorming

| # | Decision |
| --- | --- |
| B1 | **Clean slate** — the 2026-06-30 analyst-console spec is superseded, not evolved. |
| B2 | **Audience: hybrid** — a beautiful showcase level (map + imagery time travel) that opens into an analytical drill-down (dashboard view). |
| B3 | **Layout: variant A** — fullscreen Leaflet map · left sidebar (3 reservoir buttons + Dashboard button) · full-width docked timeline with area sparkline · vertical area meter pinned to the map's right edge. |
| B4 | **Motion: fully animated** — GSAP is a first-class architectural concern; everything meaningful moves (see motion score). |
| B5 | **Stack: animated-app architecture** — React + TS + Leaflet + GSAP (`@gsap/react`) + Zustand + TanStack Query; custom CSS design tokens, **no Tailwind/shadcn**. |
| B6 | **SAR imagery is real** — the time slider swaps live Earth Engine tile layers (Sentinel-1 VH per acquisition date), not synthetic polygons. Graceful fallback when GEE is unavailable. |
| B7 | **Area is the v1 meter variable** — level/storage/fill meters follow when the Stage-2 estimator lands; the meter component is built variable-agnostic. |

## Architecture

### Shell and state

One fullscreen shell: persistent left **Sidebar**, and a **Stage** hosting either the
**Map view** (default) or the **Dashboard view**. Switching views is a GSAP transition,
not a route change. UI state is a small Zustand store:

```ts
{ view: 'map' | 'dashboard',
  selected: 'gobind_sagar' | 'pong' | 'thein' | null,
  activeDate: string | null,          // drives SAR tiles + meter
  playing: boolean }                  // timeline auto-play
```

Server state goes through TanStack Query hooks — per-date tile URLs and series are cached
by `(reservoirId, date)` so scrubbing is instant after first visit.

### Map view flow

Reservoir button click → `selected` changes → GSAP-eased Leaflet `flyTo` the reservoir
AOI → timeline dock loads that reservoir's acquisition series → `activeDate` defaults to
the latest scene. Scrubbing sets `activeDate` → SAR tile layer crossfades (two stacked
`L.tileLayer`s, GSAP opacity) → area meter eases to that date's area.

### New API endpoints (read-only, additive, no contract bump)

1. `GET /reservoirs/{id}/acquisitions` → `[{date, area_km2, separability, status}]`
   — timeline + sparkline source, from `observation`.
2. `GET /reservoirs/{id}/sar-tiles?date=YYYY-MM-DD` → `{tile_url, expires_at}`
   — mints a live EE tile URL (`ee.Image.getMapId`, S1 VH styled dark) for that date's
   scene. EE map IDs expire (~4 h): server caches per `(reservoir, date)` with TTL;
   client re-requests on expiry. **503 when GEE credentials are absent** — UI falls back
   to basemap + AOI outline with a "live imagery unavailable" chip.
3. `GET /reservoirs/{id}/rainfall?window=` → daily catchment precipitation for the
   dashboard (from `catchment_forcing`; honest "awaiting live forcing" empty state until
   real ERA5 ingest runs).

### Data prerequisite

`scripts/load_backfill.py` — upserts `data/backfill/area_series_<slug>.csv` into
`observation` (real scene ids, `extraction_method='otsu_vh'`, per-scene processing stats;
abstained/error scenes are **not** loaded as areas). This replaces the stub observations
with the dense real series and is what endpoint 1 serves.

### Component structure

```
web/src/
  main.tsx
  App.tsx                    # shell: <Sidebar/> + <Stage/> — layout only
  styles/tokens.css          # design tokens: color, spacing, type, easing curves
  lib/
    store.ts                 # Zustand store
    queries.ts               # TanStack Query hooks (acquisitions, sarTile, rainfall, status)
    api.ts                   # typed fetch client (AbortSignal-aware, kept)
    motion.ts                # ALL GSAP timelines, keyed by event
  components/
    Sidebar.tsx              # brand + 3 ReservoirButton + DashboardButton
    ReservoirButton.tsx      # name, basin, live fill chip
    stage/
      MapView.tsx            # Leaflet + SarTileLayer + AoiOutline + TimelineDock + AreaMeter
      SarTileLayer.tsx       # stacked tile layers, crossfade on activeDate change
      TimelineDock.tsx       # SVG sparkline + scrub track + play button + date readout
      AreaMeter.tsx          # vertical gauge, min/max ticks from series, variable-agnostic
      DashboardView.tsx      # grid: FleetAreaChart, FillCards, LevelCards, RainfallPanel
```

`lib/motion.ts` is the load-bearing choice for "fully animated": every GSAP timeline is
defined in one module (`flyToReservoir`, `scrubCrossfade`, `meterTo`, `enterDashboard`,
`countTo`, …); components trigger them via `useGSAP`. One place to tune the whole motion
language.

## Motion score

| Moment | Animation |
| --- | --- |
| App load | Sidebar slides in; map fades from black like a satellite feed acquiring; buttons stagger in |
| Reservoir click | Eased camera flyTo; button expands with highlight sweep; meter fills from empty; timeline dock rises from bottom edge |
| Timeline scrub | SAR tile crossfade (300 ms); meter eases to new area; date readout ticks; sparkline cursor glides |
| Play button | Auto-advance ~600 ms/step through all acquisitions — ten years of seasons breathing; the showcase moment |
| Number updates | KPIs count up/down (`countTo`), never snap |
| Dashboard enter | Map scales back and dims; panels stagger in (60 ms cascade); charts draw left-to-right on first view |
| Meter idle | Slow sine water-surface shimmer — alive, not distracting |
| Abstained dates | Hollow timeline tick; meter holds with a brief amber pulse — absence shown, never faked |

## Honesty & failure states

- Per-source degradation (remediation principle carried forward): tile endpoint down →
  basemap + AOI outline + chip; rainfall empty → "awaiting live forcing"; every panel has
  skeleton → data → error states.
- Abstained scenes are visible gaps in the timeline and meter — never interpolated.
- Forecast/release-risk UI stays out (Phase-1 rescope); dashboard covers SAR area series
  (all reservoirs), fill %, level vs FRL (bulletin history now, estimator later), rainfall.

## Testing & verification

- `tsc --noEmit && vite build` stays the CI gate (web job added to CI this morning).
- New endpoints: pytest TestClient coverage incl. tile-URL TTL cache and the 503 path.
- Store transitions: 3–4 Vitest tests (scrub past end; switch reservoir mid-play;
  dashboard toggle mid-scrub).
- Motion: verified by a scripted manual smoke pass (documented in the plan), not unit tests.

## Risks & notes

- **EE tile latency/quota:** first tile view per date hits EE live; mitigated by TTL cache,
  TanStack cache, and prefetching the next few dates while playing. If quota becomes a
  problem, the fallback is pre-exported static tiles for the top-N dates (out of scope v1).
- **New deps:** gsap, @gsap/react, zustand, @tanstack/react-query — all isolated to `web/`.
- **API gains an optional GEE dependency** (endpoint 2 only), guarded so the API runs
  fully without credentials — important for CI and non-GEE deploys.
- The current dashboard's remediated behaviors (abort-safe fetches, per-source errors,
  polling) are preserved in the new `api.ts`/`queries.ts` layer.
