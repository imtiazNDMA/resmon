# Frontend Analyst Console — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the thin two-pane dashboard with a dense, map-centric **analyst console** — left control sidebar, full-bleed map with before/after imagery swipe, collapsible analytics drawer, and a bottom timeline of every SAR acquisition — backed by two new read-only API endpoints.

**Architecture:** Frontend is React + Vite + TypeScript with **Tailwind CSS + shadcn/ui**, **TanStack Query** for server state, and a small **Zustand** store for cross-cutting UI state (selected reservoir, active date, before/after pins, layer toggles, panel open/closed). The map stays on Leaflet/react-leaflet; charts stay on Recharts. Two new FastAPI endpoints serve per-acquisition metadata and a per-date water polygon; for dates without a real mask, the polygon is **derived server-side** by scaling the one real mask about its centroid to that date's measured area (flagged `derived: true`), so the UI is identical when real masks land later.

**Tech Stack:** React 18, Vite 5, TypeScript 5, Tailwind CSS 3, shadcn/ui (Radix), TanStack Query 5, Zustand 5, Leaflet 1.9 / react-leaflet 4, Recharts 2. Backend: FastAPI, SQLAlchemy 2 (raw `text()` SQL), PostGIS.

## Global Constraints

- Backend endpoints are **read-only** and **additive** — no DB migration, no `contract_version` bump. The serving layer never writes (NFR-SEC-3).
- All numeric values returned by the API must be JSON **numbers**, not `Decimal`/strings — coerce with the existing `_f()` helper (the frontend calls `.toFixed`).
- Frontend new dependencies are isolated to `web/` only.
- Dark analyst theme; the 4-tier risk palette must stay colour-blind-safe (reuse `RISK_COLOR`).
- A visible **"derived"** badge must appear whenever a synthetic (non-real) water mask is displayed (honesty per ADR-0005). A visible **staleness** banner when `data_age_days > 14` (D8).
- Build gate per task touching `web/`: `cd web && npm run build` (`tsc --noEmit && vite build`) must pass clean.
- Backend test command (DB must be up + migrated): from repo root with `DATABASE_URL_RW`/`DATABASE_URL_RO` set to the local PostGIS on `localhost:55432`, run `uv run pytest tests/integration/test_api.py -q`.
- Commit after every task. We are on branch `build/v1`.

---

## File structure

**Backend (modify only):**
- `api/src/api/repositories.py` — add `acquisitions(s, rid)` and `water_extent_by_date(s, rid, d)`.
- `api/src/api/routes.py` — add `GET /reservoirs/{rid}/acquisitions` and `GET /reservoirs/{rid}/water-extent`.
- `tests/integration/test_api.py` — add tests for both endpoints (incl. the derived-scaling path).

**Frontend (the overhaul):**
```
web/
  package.json                 # +deps (modify)
  tailwind.config.js           # create
  postcss.config.js            # create
  components.json              # create (shadcn config)
  tsconfig.json                # modify: add "@/*" path alias
  vite.config.ts               # modify: add "@" resolve alias
  index.html                   # modify: class="dark", title
  src/
    main.tsx                   # modify: QueryClientProvider + index.css
    index.css                  # create: tailwind layers + theme tokens (replaces styles.css)
    App.tsx                    # rewrite: layout shell only
    types.ts                   # modify: + Acquisition, WaterExtentFeature
    lib/
      utils.ts                 # create: cn() (shadcn helper)
      format.ts                # create: fx() numeric coercion
      risk.ts                  # create: RISK_COLOR + labels (moved from types.ts)
      api.ts                   # move from src/api.ts; + acquisitions, waterExtentByDate
      queries.ts               # create: TanStack Query hooks
      store.ts                 # create: Zustand UI store
    components/
      ui/                      # shadcn primitives (button, card, slider, tabs, switch, badge, tooltip, scroll-area, separator)
      layout/
        TopBar.tsx
        ControlSidebar.tsx
        AnalyticsDrawer.tsx
        AcquisitionTimeline.tsx
      map/
        MapCanvas.tsx
        ReservoirMarkers.tsx
        WaterExtentLayer.tsx
        BeforeAfterSwipe.tsx
        MapLegend.tsx
      panels/
        KpiGrid.tsx
        TrendChart.tsx          # adapt from existing
        ForecastChart.tsx       # adapt from existing
        ReleaseRiskPanel.tsx
        AccuracyPanel.tsx
        DataTable.tsx
  src/styles.css               # delete at end
  src/components/ReservoirMap.tsx   # delete at end (replaced by map/*)
```

**Shared type contracts (defined once, referenced everywhere):**
```ts
// web/src/types.ts (additions)
export interface Acquisition {
  date: string;                 // YYYY-MM-DD
  surface_area_km2: number;
  pct_filled: number | null;    // derived_volume / live_capacity_bcm * 100
  area_confidence: number;      // 0..1
  has_real_mask: boolean;
}
export interface WaterExtentFeature {
  type: "Feature";
  geometry: import("geojson").MultiPolygon | import("geojson").Polygon | null;
  properties: { reservoir_id: string; date: string; surface_area_km2: number; derived: boolean };
}
```

---

## Phase A — Backend endpoints (do first; strict TDD)

### Task A1: `acquisitions` endpoint

**Files:**
- Modify: `api/src/api/repositories.py` (add `acquisitions`)
- Modify: `api/src/api/routes.py` (add route)
- Test: `tests/integration/test_api.py` (add `test_acquisitions`)

**Interfaces:**
- Produces (repo): `acquisitions(s: Session, rid: str) -> list[dict]` → rows `{date, surface_area_km2, pct_filled, area_confidence, has_real_mask}` ordered by date ascending.
- Produces (HTTP): `GET /reservoirs/{rid}/acquisitions` → JSON array of the above.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_api.py  (append)
def test_acquisitions(client):
    r = client.get("/reservoirs/pong/acquisitions")
    assert r.status_code == 200
    body = r.json()
    assert len(body) > 0
    first = body[0]
    assert set(first) == {"date", "surface_area_km2", "pct_filled", "area_confidence", "has_real_mask"}
    # JSON numbers, not Decimal strings
    assert isinstance(first["surface_area_km2"], (int, float))
    assert isinstance(first["has_real_mask"], bool)
    # ascending by date
    dates = [a["date"] for a in body]
    assert dates == sorted(dates)
    # exactly the latest acquisition carries the one real mask (per the GEE populate step / fixture)
    assert sum(1 for a in body if a["has_real_mask"]) <= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_api.py::test_acquisitions -q`
Expected: FAIL — 404 / route not defined.

- [ ] **Step 3: Add the repository function**

```python
# api/src/api/repositories.py  (append)
def acquisitions(s: Session, rid: str) -> list[dict]:
    """Every SAR observation for a reservoir (drives the timeline + date pickers)."""
    rows = (
        s.execute(
            text(
                """
                SELECT o.acquisition_date AS date, o.surface_area, o.area_confidence,
                       o.derived_volume, (o.water_mask_geom IS NOT NULL) AS has_real_mask,
                       r.live_capacity_bcm
                FROM observation o
                JOIN reservoir r ON r.reservoir_id = o.reservoir_id
                WHERE o.reservoir_id = :r
                ORDER BY o.acquisition_date
                """
            ),
            {"r": rid},
        )
        .mappings()
        .all()
    )
    out: list[dict] = []
    for r in rows:
        cap = r["live_capacity_bcm"]
        vol = r["derived_volume"]
        pct = float(vol) / float(cap) * 100.0 if (vol is not None and cap) else None
        out.append(
            {
                "date": r["date"],
                "surface_area_km2": _f(r["surface_area"]),
                "pct_filled": pct,
                "area_confidence": _f(r["area_confidence"]),
                "has_real_mask": bool(r["has_real_mask"]),
            }
        )
    return out
```

- [ ] **Step 4: Add the route**

```python
# api/src/api/routes.py  (add after reservoir_timeseries)
@router.get("/reservoirs/{rid}/acquisitions", tags=["reservoirs"])
def reservoir_acquisitions(rid: str, db: Session = Depends(get_db)) -> list[dict]:
    """Every SAR acquisition (date, area, fill, mask availability) for the timeline."""
    return repo.acquisitions(db, rid)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_api.py::test_acquisitions -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/src/api/repositories.py api/src/api/routes.py tests/integration/test_api.py
git commit -m "feat(api): /reservoirs/{id}/acquisitions for the timeline"
```

---

### Task A2: per-date water-extent endpoint with derived scaling

**Files:**
- Modify: `api/src/api/repositories.py` (add `water_extent_by_date`)
- Modify: `api/src/api/routes.py` (add route + 404)
- Test: `tests/integration/test_api.py` (add `test_water_extent_by_date`)

**Interfaces:**
- Consumes: `acquisitions` (to pick a real-mask date and a no-mask date in the test).
- Produces (repo): `water_extent_by_date(s, rid, d) -> dict | None` → `None` if the (reservoir, date) observation does not exist; else `{surface_area, g, derived}` where `g` is GeoJSON text (may be `None` if no real mask exists anywhere to scale from).
- Produces (HTTP): `GET /reservoirs/{rid}/water-extent?date=YYYY-MM-DD` → a single GeoJSON `Feature` `{type, geometry, properties:{reservoir_id, date, surface_area_km2, derived}}`; 404 if the date has no observation.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_api.py  (append)
def test_water_extent_by_date(client):
    acqs = client.get("/reservoirs/pong/acquisitions").json()
    real = next(a for a in acqs if a["has_real_mask"])
    synth = next(a for a in acqs if not a["has_real_mask"])

    # real date → derived False, geometry present
    rr = client.get(f"/reservoirs/pong/water-extent?date={real['date']}")
    assert rr.status_code == 200
    fr = rr.json()
    assert fr["type"] == "Feature"
    assert fr["properties"]["derived"] is False
    assert fr["geometry"] is not None

    # synthetic date → derived True, geometry present (scaled from the one real mask)
    rs = client.get(f"/reservoirs/pong/water-extent?date={synth['date']}")
    assert rs.status_code == 200
    fs = rs.json()
    assert fs["properties"]["derived"] is True
    assert fs["geometry"] is not None
    assert isinstance(fs["properties"]["surface_area_km2"], (int, float))

    # unknown date → 404
    assert client.get("/reservoirs/pong/water-extent?date=1990-01-01").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_api.py::test_water_extent_by_date -q`
Expected: FAIL — route not defined.

- [ ] **Step 3: Add the repository function**

```python
# api/src/api/repositories.py  (append)
def water_extent_by_date(s: Session, rid: str, d: date) -> dict | None:
    """Water polygon for one acquisition date.

    Real mask if present; otherwise the single real mask scaled about its centroid to this
    date's measured area (``derived: true``). Scaling factor is ``sqrt(target/source)``
    because area grows with the square of linear size. Returns ``None`` if the (reservoir,
    date) observation does not exist (router → 404).
    """
    target = (
        s.execute(
            text(
                """
                SELECT surface_area,
                       ST_AsGeoJSON(water_mask_geom) AS g,
                       (water_mask_geom IS NOT NULL) AS has_mask
                FROM observation
                WHERE reservoir_id = :r AND acquisition_date = :d
                """
            ),
            {"r": rid, "d": d},
        )
        .mappings()
        .first()
    )
    if target is None:
        return None
    if target["has_mask"]:
        return {"surface_area": target["surface_area"], "g": target["g"], "derived": False}

    # Derive: scale the latest real mask about its own centroid to the target area.
    row = (
        s.execute(
            text(
                """
                WITH src AS (
                    SELECT water_mask_geom AS g, surface_area AS a
                    FROM observation
                    WHERE reservoir_id = :r AND water_mask_geom IS NOT NULL
                    ORDER BY acquisition_date DESC
                    LIMIT 1
                )
                SELECT ST_AsGeoJSON(
                    ST_Translate(
                        ST_Scale(
                            ST_Translate(src.g,
                                -ST_X(ST_Centroid(src.g)), -ST_Y(ST_Centroid(src.g))),
                            sqrt(:tgt / src.a), sqrt(:tgt / src.a)),
                        ST_X(ST_Centroid(src.g)), ST_Y(ST_Centroid(src.g)))
                ) AS g
                FROM src
                """
            ),
            {"r": rid, "tgt": float(target["surface_area"])},
        )
        .mappings()
        .first()
    )
    g = row["g"] if row else None  # None when no real mask exists anywhere to scale from
    return {"surface_area": target["surface_area"], "g": g, "derived": True}
```

- [ ] **Step 4: Add the route**

```python
# api/src/api/routes.py  (add after geojson_water_extent; needs `from datetime import date`)
@router.get("/reservoirs/{rid}/water-extent", tags=["reservoirs"])
def reservoir_water_extent(
    rid: str, date: date = Query(...), db: Session = Depends(get_db)
) -> dict:
    """Water polygon for one acquisition date (real, or derived from the latest real mask)."""
    row = repo.water_extent_by_date(db, rid, date)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no acquisition for {rid!r} on {date}")
    return {
        "type": "Feature",
        "geometry": json.loads(row["g"]) if row["g"] else None,
        "properties": {
            "reservoir_id": rid,
            "date": str(date),
            "surface_area_km2": float(row["surface_area"]),
            "derived": bool(row["derived"]),
        },
    }
```
Add `from datetime import date` to the imports at the top of `routes.py`.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_api.py::test_water_extent_by_date -q`
Expected: PASS.

- [ ] **Step 6: Run the whole API suite + lint/type**

Run: `uv run pytest tests/integration/test_api.py -q && uv run ruff check api && uv run mypy api`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add api/src/api/repositories.py api/src/api/routes.py tests/integration/test_api.py
git commit -m "feat(api): per-date water-extent with server-side derived-mask scaling"
```

---

## Phase B — Frontend foundation

### Task B1: Tailwind + path alias + dark theme tokens

**Files:**
- Modify: `web/package.json` (devDeps)
- Create: `web/tailwind.config.js`, `web/postcss.config.js`, `web/src/index.css`, `web/src/lib/utils.ts`
- Modify: `web/tsconfig.json`, `web/vite.config.ts`, `web/index.html`, `web/src/main.tsx`

**Interfaces:**
- Produces: Tailwind utility classes available app-wide; `@/` resolves to `web/src/`; `cn()` class-merge helper; CSS theme variables for shadcn.

- [ ] **Step 1: Install dependencies**

Run:
```bash
cd web && npm install -D tailwindcss@3 postcss autoprefixer && \
npm install class-variance-authority clsx tailwind-merge lucide-react
```

- [ ] **Step 2: Create `web/postcss.config.js`**

```js
export default { plugins: { tailwindcss: {}, autoprefixer: {} } };
```

- [ ] **Step 3: Create `web/tailwind.config.js`**

```js
/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
      },
      borderRadius: { lg: "var(--radius)", md: "calc(var(--radius) - 2px)", sm: "calc(var(--radius) - 4px)" },
    },
  },
  plugins: [],
};
```

- [ ] **Step 4: Create `web/src/index.css`** (dark analyst theme)

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 215 40% 8%;     --foreground: 210 30% 92%;
    --card: 215 35% 11%;          --card-foreground: 210 30% 92%;
    --primary: 199 89% 55%;       --primary-foreground: 215 40% 8%;
    --secondary: 215 30% 18%;     --secondary-foreground: 210 30% 92%;
    --muted: 215 25% 16%;         --muted-foreground: 215 15% 60%;
    --accent: 199 89% 55%;        --accent-foreground: 215 40% 8%;
    --border: 215 25% 20%;        --input: 215 25% 20%;  --ring: 199 89% 55%;
    --radius: 0.5rem;
  }
  * { @apply border-border; }
  html, body, #root { height: 100%; margin: 0; }
  body { @apply bg-background text-foreground; font-family: system-ui, "Segoe UI", Roboto, sans-serif; }
}
```

- [ ] **Step 5: Create `web/src/lib/utils.ts`**

```ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 6: Add the `@/` alias**

In `web/tsconfig.json`, add to `compilerOptions`:
```json
"baseUrl": ".",
"paths": { "@/*": ["./src/*"] }
```
In `web/vite.config.ts`, add `import path from "node:path";` and inside `defineConfig({...})` add:
```ts
resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
```

- [ ] **Step 7: Switch entry to `index.css` + dark class**

In `web/src/main.tsx` replace `import "./styles.css";` with `import "./index.css";` (keep the leaflet import).
In `web/index.html` set `<html lang="en" class="dark">`.

- [ ] **Step 8: Verify build**

Run: `cd web && npm run build`
Expected: PASS (app still renders old `App.tsx`, now on Tailwind base).

- [ ] **Step 9: Commit**

```bash
git add web/package.json web/package-lock.json web/tailwind.config.js web/postcss.config.js \
  web/src/index.css web/src/lib/utils.ts web/tsconfig.json web/vite.config.ts web/index.html web/src/main.tsx
git commit -m "build(web): Tailwind + dark theme tokens + @/ alias"
```

---

### Task B2: shadcn/ui primitives + TanStack Query + Zustand providers

**Files:**
- Modify: `web/package.json`
- Create: `web/components.json`, `web/src/components/ui/*` (button, card, badge, slider, tabs, switch, tooltip, scroll-area, separator)
- Modify: `web/src/main.tsx` (QueryClientProvider)

**Interfaces:**
- Produces: importable shadcn primitives under `@/components/ui/*`; a `QueryClient` wrapping the app.

- [ ] **Step 1: Install dependencies**

Run:
```bash
cd web && npm install @tanstack/react-query zustand \
  @radix-ui/react-slider @radix-ui/react-tabs @radix-ui/react-switch \
  @radix-ui/react-tooltip @radix-ui/react-scroll-area @radix-ui/react-separator
```

- [ ] **Step 2: Create `web/components.json`** (so future `npx shadcn add` works)

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "default", "rsc": false, "tsx": true,
  "tailwind": { "config": "tailwind.config.js", "css": "src/index.css", "baseColor": "slate", "cssVariables": true },
  "aliases": { "components": "@/components", "utils": "@/lib/utils", "ui": "@/components/ui" }
}
```

- [ ] **Step 3: Add the shadcn primitives**

Run: `cd web && npx shadcn@latest add button card badge slider tabs switch tooltip scroll-area separator --yes`
Expected: files created under `web/src/components/ui/`. If the CLI prompts or fails offline, copy the component sources from ui.shadcn.com for each named primitive into `web/src/components/ui/<name>.tsx` (they depend only on the Radix packages installed in Step 1 + `cn`).

- [ ] **Step 4: Wrap the app in QueryClientProvider**

```tsx
// web/src/main.tsx  (final form)
import "leaflet/dist/leaflet.css";
import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 60_000, refetchOnWindowFocus: false } },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 5: Verify build**

Run: `cd web && npm run build`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/package.json web/package-lock.json web/components.json web/src/components/ui web/src/main.tsx
git commit -m "build(web): shadcn/ui primitives + TanStack Query provider"
```

---

### Task B3: data layer — types, api client, query hooks, store, libs

**Files:**
- Modify: `web/src/types.ts`
- Create: `web/src/lib/risk.ts`, `web/src/lib/format.ts`, `web/src/lib/api.ts`, `web/src/lib/queries.ts`, `web/src/lib/store.ts`
- Delete later: `web/src/api.ts` (moved into `lib/api.ts`)

**Interfaces:**
- Produces:
  - `lib/format.ts`: `fx(v, digits=1): string`
  - `lib/risk.ts`: `RISK_COLOR: Record<RiskLevel,string>`, `RISK_LEVELS: RiskLevel[]`
  - `lib/api.ts`: `api.*` incl. `acquisitions(id)`, `waterExtentByDate(id, date)`
  - `lib/queries.ts`: hooks `useReservoirs, useFleetRisk, useReservoirGeojson, useAoi, useCatchment, useStatus(id), useTimeseries(id), useForecast(id), useAccuracy, useAcquisitions(id), useWaterExtentByDate(id, date)`
  - `lib/store.ts`: `useUi()` Zustand store (shape below)

- [ ] **Step 1: Extend `web/src/types.ts`**

Add the `Acquisition` and `WaterExtentFeature` interfaces (verbatim from the "Shared type contracts" block above). Keep all existing interfaces. Remove the `RISK_COLOR` export from `types.ts` (it moves to `lib/risk.ts` in Step 2).

- [ ] **Step 2: Create `web/src/lib/risk.ts`**

```ts
import type { RiskLevel } from "@/types";

export const RISK_LEVELS: RiskLevel[] = ["Low", "Watch", "Warning", "Imminent"];
export const RISK_COLOR: Record<RiskLevel, string> = {
  Low: "#2c7fb8", Watch: "#fec44f", Warning: "#fe9929", Imminent: "#d7301f",
};
```

- [ ] **Step 3: Create `web/src/lib/format.ts`**

```ts
export const fx = (v: number | string | null | undefined, digits = 1): string =>
  v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(digits);
```

- [ ] **Step 4: Create `web/src/lib/api.ts`** (move + extend the old `src/api.ts`)

```ts
import type {
  Acquisition, FeatureCollection, FleetRisk, Forecast, GeoFC,
  Reservoir, Status, TimeseriesPoint, WaterExtentFeature,
} from "@/types";

const BASE = "/api";
async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return (await res.json()) as T;
}

export const api = {
  reservoirs: () => getJson<Reservoir[]>("/reservoirs"),
  status: (id: string) => getJson<Status>(`/reservoirs/${id}/status`),
  timeseries: (id: string, limit = 400) =>
    getJson<TimeseriesPoint[]>(`/reservoirs/${id}/timeseries?limit=${limit}`),
  forecast: (id: string) => getJson<Forecast>(`/reservoirs/${id}/forecast`),
  fleetRisk: () => getJson<FleetRisk[]>("/release-risk"),
  accuracy: () => getJson<unknown>("/accuracy"),
  geojson: () => getJson<FeatureCollection>("/geojson/reservoirs"),
  aoi: () => getJson<GeoFC>("/geojson/aoi"),
  catchment: () => getJson<GeoFC>("/geojson/catchment"),
  acquisitions: (id: string) => getJson<Acquisition[]>(`/reservoirs/${id}/acquisitions`),
  waterExtentByDate: (id: string, date: string) =>
    getJson<WaterExtentFeature>(`/reservoirs/${id}/water-extent?date=${date}`),
};
```

- [ ] **Step 5: Create `web/src/lib/queries.ts`**

```ts
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export const useReservoirs = () => useQuery({ queryKey: ["reservoirs"], queryFn: api.reservoirs });
export const useFleetRisk = () => useQuery({ queryKey: ["fleet"], queryFn: api.fleetRisk });
export const useReservoirGeojson = () => useQuery({ queryKey: ["geojson"], queryFn: api.geojson });
export const useAoi = () => useQuery({ queryKey: ["aoi"], queryFn: api.aoi });
export const useCatchment = () => useQuery({ queryKey: ["catchment"], queryFn: api.catchment });
export const useAccuracy = () => useQuery({ queryKey: ["accuracy"], queryFn: api.accuracy });

export const useStatus = (id: string | null) =>
  useQuery({ queryKey: ["status", id], queryFn: () => api.status(id!), enabled: !!id });
export const useTimeseries = (id: string | null) =>
  useQuery({ queryKey: ["timeseries", id], queryFn: () => api.timeseries(id!), enabled: !!id });
export const useForecast = (id: string | null) =>
  useQuery({ queryKey: ["forecast", id], queryFn: () => api.forecast(id!), enabled: !!id });
export const useAcquisitions = (id: string | null) =>
  useQuery({ queryKey: ["acquisitions", id], queryFn: () => api.acquisitions(id!), enabled: !!id });
export const useWaterExtentByDate = (id: string | null, date: string | null) =>
  useQuery({
    queryKey: ["water-extent", id, date],
    queryFn: () => api.waterExtentByDate(id!, date!),
    enabled: !!id && !!date,
  });
```

- [ ] **Step 6: Create `web/src/lib/store.ts`**

```ts
import { create } from "zustand";

export interface LayerState { aoi: boolean; water: boolean; catchment: boolean; markers: boolean }
export interface UiState {
  selectedReservoir: string | null;
  activeDate: string | null;
  compareMode: boolean;
  compare: { before: string | null; after: string | null };
  layers: LayerState;
  sidebarOpen: boolean;
  drawerOpen: boolean;
  select: (id: string) => void;
  setActiveDate: (d: string) => void;
  toggleCompare: () => void;
  setCompare: (slot: "before" | "after", d: string) => void;
  toggleLayer: (k: keyof LayerState) => void;
  setSidebar: (v: boolean) => void;
  setDrawer: (v: boolean) => void;
}

export const useUi = create<UiState>((set) => ({
  selectedReservoir: null,
  activeDate: null,
  compareMode: false,
  compare: { before: null, after: null },
  layers: { aoi: true, water: true, catchment: false, markers: true },
  sidebarOpen: true,
  drawerOpen: true,
  select: (id) => set({ selectedReservoir: id, activeDate: null, compare: { before: null, after: null } }),
  setActiveDate: (d) => set({ activeDate: d }),
  toggleCompare: (s) => set((st) => ({ compareMode: !st.compareMode })),
  setCompare: (slot, d) => set((st) => ({ compare: { ...st.compare, [slot]: d } })),
  toggleLayer: (k) => set((st) => ({ layers: { ...st.layers, [k]: !st.layers[k] } })),
  setSidebar: (v) => set({ sidebarOpen: v }),
  setDrawer: (v) => set({ drawerOpen: v }),
}));
```
> Note: fix the `toggleCompare` signature to `() =>` (no arg) — shown with `(s)` by mistake; use `toggleCompare: () => set((st) => ({ compareMode: !st.compareMode }))`.

- [ ] **Step 7: Verify build**

Run: `cd web && npm run build`
Expected: PASS (nothing imports these yet; tsc checks them).

- [ ] **Step 8: Commit**

```bash
git add web/src/types.ts web/src/lib
git commit -m "feat(web): data layer — types, api client, query hooks, ui store"
```

---

## Phase C — Layout shell

### Task C1: App shell + TopBar

**Files:**
- Rewrite: `web/src/App.tsx`
- Create: `web/src/components/layout/TopBar.tsx`

**Interfaces:**
- Consumes: `useUi`, `useReservoirs`, `useFleetRisk`, `useStatus`, `RISK_COLOR`.
- Produces: `<App/>` rendering a CSS-grid shell with named slots; `<TopBar/>` (brand + fleet chips + freshness). On first reservoir load, the shell calls `useUi().select(first.id)` if none selected.

- [ ] **Step 1: Create `web/src/components/layout/TopBar.tsx`**

```tsx
import { useFleetRisk, useReservoirs, useStatus } from "@/lib/queries";
import { RISK_COLOR } from "@/lib/risk";
import { useUi } from "@/lib/store";
import { cn } from "@/lib/utils";

export function TopBar() {
  const { data: fleet = [] } = useFleetRisk();
  const { data: reservoirs = [] } = useReservoirs();
  const { selectedReservoir, select } = useUi();
  const { data: status } = useStatus(selectedReservoir);
  const name = (id: string) => reservoirs.find((r) => r.reservoir_id === id)?.name ?? id;

  return (
    <header className="flex items-center justify-between gap-4 border-b border-border bg-card px-4 py-2">
      <div className="flex items-center gap-2">
        <span className="text-2xl text-primary">◉</span>
        <div>
          <div className="text-sm font-bold tracking-tight">Reservoir Monitoring &amp; Analytics</div>
          <div className="text-[11px] text-muted-foreground">SAR-derived storage · release-risk early warning</div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {fleet.map((f) => (
          <button
            key={f.reservoir_id}
            onClick={() => select(f.reservoir_id)}
            className={cn(
              "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs",
              f.reservoir_id === selectedReservoir ? "bg-secondary" : "bg-transparent",
            )}
            style={{ borderColor: RISK_COLOR[f.risk_level] }}
          >
            <span className="h-2 w-2 rounded-full" style={{ background: RISK_COLOR[f.risk_level] }} />
            {name(f.reservoir_id)}
            <span className="text-muted-foreground">{f.risk_level}</span>
          </button>
        ))}
      </div>
      <div className="text-xs text-muted-foreground">
        {status?.stale ? (
          <span className="text-amber-400">⏳ {status.data_age_days}d old</span>
        ) : (
          <span>● live</span>
        )}
      </div>
    </header>
  );
}
```

- [ ] **Step 2: Rewrite `web/src/App.tsx` as the shell**

```tsx
import { useEffect } from "react";

import { AcquisitionTimeline } from "@/components/layout/AcquisitionTimeline";
import { AnalyticsDrawer } from "@/components/layout/AnalyticsDrawer";
import { ControlSidebar } from "@/components/layout/ControlSidebar";
import { TopBar } from "@/components/layout/TopBar";
import { MapCanvas } from "@/components/map/MapCanvas";
import { useReservoirs } from "@/lib/queries";
import { useUi } from "@/lib/store";

export default function App() {
  const { data: reservoirs = [] } = useReservoirs();
  const { selectedReservoir, select, sidebarOpen, drawerOpen } = useUi();

  useEffect(() => {
    if (!selectedReservoir && reservoirs.length > 0) select(reservoirs[0].reservoir_id);
  }, [reservoirs, selectedReservoir, select]);

  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        {sidebarOpen && <ControlSidebar />}
        <main className="relative min-w-0 flex-1">
          <MapCanvas />
        </main>
        {drawerOpen && <AnalyticsDrawer />}
      </div>
      <AcquisitionTimeline />
    </div>
  );
}
```
> The four child components are built in C2–C4 and D1. To keep the build green between tasks, create thin placeholder files for `ControlSidebar`, `AnalyticsDrawer`, `AcquisitionTimeline`, `MapCanvas` now, each `export function X(){ return <div/> }`, and flesh them out in their tasks.

- [ ] **Step 3: Verify build**

Run: `cd web && npm run build`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add web/src/App.tsx web/src/components/layout/TopBar.tsx web/src/components/layout web/src/components/map
git commit -m "feat(web): app shell + topbar (placeholders for regions)"
```

---

### Task C2: ControlSidebar (reservoir + layers + imagery controls)

**Files:**
- Create: `web/src/components/layout/ControlSidebar.tsx`
- Create: `web/src/components/map/LayerToggles.tsx`

**Interfaces:**
- Consumes: `useUi` (layers, compareMode, compare, activeDate, select), `useReservoirs`, `useAcquisitions`, shadcn `Switch`, `Button`, `Separator`, `ScrollArea`.
- Produces: `<ControlSidebar/>` (fixed-width left column); `<LayerToggles/>` (reused list of switches).

- [ ] **Step 1: Create `web/src/components/map/LayerToggles.tsx`**

```tsx
import { Switch } from "@/components/ui/switch";
import { useUi, type LayerState } from "@/lib/store";

const ROWS: { key: keyof LayerState; label: string }[] = [
  { key: "markers", label: "Dam markers" },
  { key: "aoi", label: "Reservoir AOI (JRC GSW)" },
  { key: "water", label: "Water extent (Sentinel-1)" },
  { key: "catchment", label: "Catchment (HydroBASINS)" },
];

export function LayerToggles() {
  const { layers, toggleLayer } = useUi();
  return (
    <div className="space-y-2">
      {ROWS.map((r) => (
        <label key={r.key} className="flex items-center justify-between text-xs">
          <span>{r.label}</span>
          <Switch checked={layers[r.key]} onCheckedChange={() => toggleLayer(r.key)} />
        </label>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create `web/src/components/layout/ControlSidebar.tsx`**

```tsx
import { LayerToggles } from "@/components/map/LayerToggles";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { useAcquisitions, useReservoirs } from "@/lib/queries";
import { useUi } from "@/lib/store";
import { cn } from "@/lib/utils";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</div>
      {children}
    </div>
  );
}

export function ControlSidebar() {
  const { data: reservoirs = [] } = useReservoirs();
  const { selectedReservoir, select, compareMode, toggleCompare, compare, setCompare, activeDate } = useUi();
  const { data: acqs = [] } = useAcquisitions(selectedReservoir);
  const latest = acqs.at(-1)?.date;

  return (
    <aside className="w-72 shrink-0 border-r border-border bg-card">
      <ScrollArea className="h-full">
        <div className="space-y-5 p-3">
          <Section title="Reservoir">
            <div className="space-y-1">
              {reservoirs.map((r) => (
                <button
                  key={r.reservoir_id}
                  onClick={() => select(r.reservoir_id)}
                  className={cn(
                    "w-full rounded-md px-2 py-1.5 text-left text-sm",
                    r.reservoir_id === selectedReservoir ? "bg-secondary" : "hover:bg-secondary/50",
                  )}
                >
                  {r.name}
                  <span className="block text-[11px] text-muted-foreground">{r.basin} basin</span>
                </button>
              ))}
            </div>
          </Section>

          <Separator />
          <Section title="Layers"><LayerToggles /></Section>

          <Separator />
          <Section title="Imagery">
            <Button variant={compareMode ? "default" : "secondary"} size="sm" className="w-full"
                    onClick={toggleCompare}>
              {compareMode ? "Before / after: ON" : "Compare two dates"}
            </Button>
            {compareMode ? (
              <div className="space-y-1 text-xs">
                <div>Before: <b>{compare.before ?? "— pick on timeline"}</b></div>
                <div>After: <b>{compare.after ?? latest ?? "—"}</b></div>
                <p className="text-muted-foreground">
                  Click the timeline to set <i>before</i>; shift-click to set <i>after</i>.
                </p>
              </div>
            ) : (
              <div className="text-xs text-muted-foreground">
                Active date: <b className="text-foreground">{activeDate ?? latest ?? "—"}</b>
                <span className="block">Scrub the timeline to change.</span>
              </div>
            )}
          </Section>
        </div>
      </ScrollArea>
    </aside>
  );
}
```

- [ ] **Step 3: Verify build**

Run: `cd web && npm run build`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/layout/ControlSidebar.tsx web/src/components/map/LayerToggles.tsx
git commit -m "feat(web): control sidebar — reservoir, layers, imagery controls"
```

---

### Task C3: AcquisitionTimeline (bottom scrubber + sparkline)

**Files:**
- Create: `web/src/components/layout/AcquisitionTimeline.tsx`

**Interfaces:**
- Consumes: `useUi` (selectedReservoir, activeDate, compareMode, setActiveDate, setCompare), `useAcquisitions`, Recharts.
- Produces: `<AcquisitionTimeline/>` — a full-width bar showing the area sparkline of all acquisitions; click sets active date (or before/after in compare mode); the active date is highlighted. On first load, defaults `activeDate` to the latest acquisition.

- [ ] **Step 1: Create the component**

```tsx
import { useEffect } from "react";
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis } from "recharts";

import { useAcquisitions } from "@/lib/queries";
import { useUi } from "@/lib/store";

export function AcquisitionTimeline() {
  const { selectedReservoir, activeDate, compareMode, compare, setActiveDate, setCompare } = useUi();
  const { data: acqs = [] } = useAcquisitions(selectedReservoir);
  const latest = acqs.at(-1)?.date ?? null;

  useEffect(() => {
    if (!activeDate && latest) setActiveDate(latest);
  }, [latest, activeDate, setActiveDate]);

  const onClick = (date: string, shift: boolean) => {
    if (compareMode) setCompare(shift ? "after" : "before", date);
    else setActiveDate(date);
  };

  const data = acqs.map((a) => ({ date: a.date, area: a.surface_area_km2, real: a.has_real_mask }));

  return (
    <div className="h-28 shrink-0 border-t border-border bg-card px-3 py-1">
      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
        <span>Acquisition timeline — {acqs.length} scenes{latest ? ` · latest ${latest}` : ""}</span>
        <span>{compareMode ? `before ${compare.before ?? "—"} · after ${compare.after ?? "—"}` : `active ${activeDate ?? "—"}`}</span>
      </div>
      <ResponsiveContainer width="100%" height={78}>
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
                  onClick={(e: any) => { const p = e?.activePayload?.[0]?.payload; if (p) onClick(p.date, !!e?.shiftKey); }}>
          <XAxis dataKey="date" tick={{ fontSize: 9 }} minTickGap={60} />
          <Tooltip formatter={(v: number) => [`${Number(v).toFixed(1)} km²`, "area"]} labelStyle={{ color: "#0b1b2b" }} />
          <Bar dataKey="area">
            {data.map((d) => (
              <Cell key={d.date}
                    fill={d.date === activeDate ? "#38bdf8" : d.real ? "#22d3ee" : "#33506e"}
                    cursor="pointer" />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
```
> Recharts' `onClick` event carries `shiftKey`; the `any` casts mirror Recharts' loose event typing (the existing charts use Recharts the same way). Real-mask scenes are tinted brighter so the analyst can see which dates have a true mask.

- [ ] **Step 2: Verify build**

Run: `cd web && npm run build`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/layout/AcquisitionTimeline.tsx
git commit -m "feat(web): bottom acquisition timeline scrubber"
```

---

### Task C4: AnalyticsDrawer (collapsible right column, panel host)

**Files:**
- Create: `web/src/components/layout/AnalyticsDrawer.tsx`

**Interfaces:**
- Consumes: `useUi` (selectedReservoir), `useReservoirs`, the Phase-E panels, shadcn `ScrollArea`, `Tabs`.
- Produces: `<AnalyticsDrawer/>` — fixed-width right column hosting KPI + tabs (Trend / Forecast / Risk / Accuracy / Data). Panels are built in Phase E; until then, import placeholders.

- [ ] **Step 1: Create the component**

```tsx
import { AccuracyPanel } from "@/components/panels/AccuracyPanel";
import { DataTable } from "@/components/panels/DataTable";
import { ForecastChart } from "@/components/panels/ForecastChart";
import { KpiGrid } from "@/components/panels/KpiGrid";
import { ReleaseRiskPanel } from "@/components/panels/ReleaseRiskPanel";
import { TrendChart } from "@/components/panels/TrendChart";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useReservoirs } from "@/lib/queries";
import { useUi } from "@/lib/store";

export function AnalyticsDrawer() {
  const { selectedReservoir } = useUi();
  const { data: reservoirs = [] } = useReservoirs();
  const res = reservoirs.find((r) => r.reservoir_id === selectedReservoir) ?? null;

  return (
    <aside className="w-[26rem] shrink-0 border-l border-border bg-card">
      <ScrollArea className="h-full">
        <div className="space-y-4 p-3">
          <div>
            <h2 className="text-lg font-semibold">{res?.name ?? "—"}</h2>
            <div className="text-xs text-muted-foreground">{res?.basin} basin</div>
          </div>
          <KpiGrid />
          <Tabs defaultValue="trend">
            <TabsList className="grid w-full grid-cols-5">
              <TabsTrigger value="trend">Trend</TabsTrigger>
              <TabsTrigger value="forecast">Forecast</TabsTrigger>
              <TabsTrigger value="risk">Risk</TabsTrigger>
              <TabsTrigger value="accuracy">Accuracy</TabsTrigger>
              <TabsTrigger value="data">Data</TabsTrigger>
            </TabsList>
            <TabsContent value="trend"><TrendChart /></TabsContent>
            <TabsContent value="forecast"><ForecastChart /></TabsContent>
            <TabsContent value="risk"><ReleaseRiskPanel /></TabsContent>
            <TabsContent value="accuracy"><AccuracyPanel /></TabsContent>
            <TabsContent value="data"><DataTable /></TabsContent>
          </Tabs>
        </div>
      </ScrollArea>
    </aside>
  );
}
```
> Create thin placeholder files for the six panels now (`export function X(){ return <div/> }`) so this builds; Phase E fills them in.

- [ ] **Step 2: Verify build**

Run: `cd web && npm run build`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/layout/AnalyticsDrawer.tsx web/src/components/panels
git commit -m "feat(web): analytics drawer shell + panel tabs"
```

---

## Phase D — Map

### Task D1: MapCanvas + ReservoirMarkers + MapLegend

**Files:**
- Create: `web/src/components/map/MapCanvas.tsx`, `web/src/components/map/ReservoirMarkers.tsx`, `web/src/components/map/MapLegend.tsx`

**Interfaces:**
- Consumes: `useReservoirGeojson`, `useAoi`, `useCatchment`, `useUi` (layers, selectedReservoir, select), `RISK_COLOR`, react-leaflet.
- Produces: `<MapCanvas/>` (full-bleed map with base layers + AOI/catchment overlays gated by `layers`, hosts `WaterExtentLayer`/`BeforeAfterSwipe` from D2/D3 + `MapLegend`); `<ReservoirMarkers/>`; `<MapLegend/>`.

- [ ] **Step 1: Create `ReservoirMarkers.tsx`**

```tsx
import { CircleMarker, Popup } from "react-leaflet";

import { useReservoirGeojson } from "@/lib/queries";
import { RISK_COLOR } from "@/lib/risk";
import { useUi } from "@/lib/store";
import type { RiskLevel } from "@/types";

export function ReservoirMarkers() {
  const { data: markers } = useReservoirGeojson();
  const { selectedReservoir, select } = useUi();
  return (
    <>
      {markers?.features.map((f) => {
        if (!f.geometry) return null;
        const [lon, lat] = f.geometry.coordinates;
        const p = f.properties;
        const level = (p.risk_level ?? "Low") as RiskLevel;
        const sel = p.reservoir_id === selectedReservoir;
        return (
          <CircleMarker key={p.reservoir_id} center={[lat, lon]} radius={sel ? 13 : 9}
            pathOptions={{ color: sel ? "#fff" : "#0b1b2b", weight: sel ? 3 : 1.5,
                           fillColor: RISK_COLOR[level], fillOpacity: 0.95 }}
            eventHandlers={{ click: () => select(p.reservoir_id) }}>
            <Popup><strong>{p.name}</strong><br />Release risk: {p.risk_level ?? "—"}</Popup>
          </CircleMarker>
        );
      })}
    </>
  );
}
```

- [ ] **Step 2: Create `MapLegend.tsx`**

```tsx
import { RISK_COLOR, RISK_LEVELS } from "@/lib/risk";

export function MapLegend() {
  return (
    <div className="absolute bottom-3 left-3 z-[1000] rounded-md border border-border bg-card/90 p-2 text-xs backdrop-blur">
      <div className="mb-1 font-semibold">Release risk</div>
      {RISK_LEVELS.map((l) => (
        <div key={l} className="flex items-center gap-2">
          <span className="h-3 w-3 rounded-sm" style={{ background: RISK_COLOR[l] }} />{l}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Create `MapCanvas.tsx`**

```tsx
import { GeoJSON, LayersControl, MapContainer, TileLayer } from "react-leaflet";

import { BeforeAfterSwipe } from "@/components/map/BeforeAfterSwipe";
import { MapLegend } from "@/components/map/MapLegend";
import { ReservoirMarkers } from "@/components/map/ReservoirMarkers";
import { WaterExtentLayer } from "@/components/map/WaterExtentLayer";
import { useAoi, useCatchment } from "@/lib/queries";
import { useUi } from "@/lib/store";

const { BaseLayer } = LayersControl;

export function MapCanvas() {
  const { layers, compareMode } = useUi();
  const { data: aoi } = useAoi();
  const { data: catchment } = useCatchment();

  return (
    <div className="relative h-full w-full">
      <MapContainer center={[31.9, 76.0]} zoom={8} style={{ height: "100%", width: "100%" }}>
        <LayersControl position="topright">
          <BaseLayer checked name="Satellite">
            <TileLayer attribution="Tiles &copy; Esri"
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}" />
          </BaseLayer>
          <BaseLayer name="Street">
            <TileLayer attribution="&copy; OpenStreetMap"
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
          </BaseLayer>
        </LayersControl>

        {layers.catchment && catchment && (
          <GeoJSON data={catchment} style={() => ({ color: "#f59e0b", weight: 1.5, fillOpacity: 0.05, dashArray: "5 5" })} />
        )}
        {layers.aoi && aoi && (
          <GeoJSON data={aoi} style={() => ({ color: "#38bdf8", weight: 2, fillOpacity: 0.08 })} />
        )}
        {layers.water && !compareMode && <WaterExtentLayer />}
        {layers.water && compareMode && <BeforeAfterSwipe />}
        {layers.markers && <ReservoirMarkers />}
      </MapContainer>
      <MapLegend />
    </div>
  );
}
```
> `WaterExtentLayer` (D2) and `BeforeAfterSwipe` (D3) must exist as placeholders for this to build; create `export function X(){ return null }` stubs now.

- [ ] **Step 4: Verify build**

Run: `cd web && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/map
git commit -m "feat(web): map canvas, markers, legend, layer gating"
```

---

### Task D2: WaterExtentLayer (active-date overlay + derived badge)

**Files:**
- Create: `web/src/components/map/WaterExtentLayer.tsx` (replace stub)

**Interfaces:**
- Consumes: `useUi` (selectedReservoir, activeDate), `useWaterExtentByDate`, react-leaflet `GeoJSON`.
- Produces: `<WaterExtentLayer/>` — renders the active date's water polygon; shows a floating **"derived"** badge when `properties.derived`. `GeoJSON` is keyed by `id|date` so it re-renders when the date changes.

- [ ] **Step 1: Create the component**

```tsx
import { GeoJSON } from "react-leaflet";

import { useWaterExtentByDate } from "@/lib/queries";
import { useUi } from "@/lib/store";

export function WaterExtentLayer() {
  const { selectedReservoir, activeDate } = useUi();
  const { data } = useWaterExtentByDate(selectedReservoir, activeDate);
  if (!data?.geometry) return null;
  return (
    <>
      <GeoJSON key={`${selectedReservoir}-${activeDate}`} data={data.geometry as GeoJSON.GeoJsonObject}
        style={() => ({ color: "#0ea5e9", weight: 1, fillColor: "#22d3ee", fillOpacity: 0.55 })} />
      {data.properties.derived && (
        <div className="absolute right-3 top-3 z-[1000] rounded-md border border-amber-500/60 bg-card/90 px-2 py-1 text-xs text-amber-400 backdrop-blur">
          ⚠ derived mask — shape scaled to measured area ({data.properties.surface_area_km2.toFixed(1)} km²)
        </div>
      )}
    </>
  );
}
```
> Importing the `GeoJSON.GeoJsonObject` type comes from the ambient `geojson` types already installed. The badge is positioned over the map (the map wrapper is `relative`).

- [ ] **Step 2: Verify build**

Run: `cd web && npm run build`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/map/WaterExtentLayer.tsx
git commit -m "feat(web): active-date water overlay + derived-mask badge"
```

---

### Task D3: BeforeAfterSwipe (two-date map comparison)

**Files:**
- Create: `web/src/components/map/BeforeAfterSwipe.tsx` (replace stub)

**Interfaces:**
- Consumes: `useUi` (selectedReservoir, compare, activeDate), `useWaterExtentByDate` (twice), react-leaflet `GeoJSON` + `useMap`.
- Produces: `<BeforeAfterSwipe/>` — renders the "before" polygon clipped to the left of a draggable vertical handle and "after" to the right, using two Leaflet panes with CSS `clip-path` driven by a handle position (0–100%). Falls back to "after" = latest when unset.

**Approach note:** react-leaflet has no built-in swipe. We render two `GeoJSON` layers into two custom panes (`pane-before`, `pane-after`) and clip each pane's container via `clip-path` based on a slider value held in component state. A simple absolutely-positioned range input over the map drives the clip. This avoids the `leaflet-side-by-side` plugin (which manipulates tile layers, not GeoJSON).

- [ ] **Step 1: Create the component**

```tsx
import { useState } from "react";
import { GeoJSON, Pane } from "react-leaflet";

import { useWaterExtentByDate } from "@/lib/queries";
import { useUi } from "@/lib/store";

export function BeforeAfterSwipe() {
  const { selectedReservoir, compare, activeDate } = useUi();
  const beforeDate = compare.before ?? activeDate;
  const afterDate = compare.after ?? activeDate;
  const { data: before } = useWaterExtentByDate(selectedReservoir, beforeDate);
  const { data: after } = useWaterExtentByDate(selectedReservoir, afterDate);
  const [split, setSplit] = useState(50);

  return (
    <>
      <Pane name="pane-before" style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }}>
        {before?.geometry && (
          <GeoJSON key={`b-${beforeDate}`} data={before.geometry as GeoJSON.GeoJsonObject}
            style={() => ({ color: "#0ea5e9", weight: 1, fillColor: "#22d3ee", fillOpacity: 0.55 })} />
        )}
      </Pane>
      <Pane name="pane-after" style={{ clipPath: `inset(0 0 0 ${split}%)` }}>
        {after?.geometry && (
          <GeoJSON key={`a-${afterDate}`} data={after.geometry as GeoJSON.GeoJsonObject}
            style={() => ({ color: "#f97316", weight: 1, fillColor: "#fb923c", fillOpacity: 0.5 })} />
        )}
      </Pane>
      <div className="pointer-events-none absolute inset-x-0 top-2 z-[1000] flex justify-between px-10 text-xs">
        <span className="rounded bg-card/90 px-2 py-0.5 text-cyan-300">before · {beforeDate} · {before?.properties.surface_area_km2.toFixed(1) ?? "—"} km²</span>
        <span className="rounded bg-card/90 px-2 py-0.5 text-orange-300">after · {afterDate} · {after?.properties.surface_area_km2.toFixed(1) ?? "—"} km²</span>
      </div>
      <input type="range" min={0} max={100} value={split} onChange={(e) => setSplit(Number(e.target.value))}
        className="absolute left-1/2 top-1/2 z-[1000] w-1/2 -translate-x-1/2" />
    </>
  );
}
```
> The two `Pane`s default to overlapping z-order above the base map; `clip-path: inset(...)` reveals each half. The range input drives the split. Both polygons may be derived — the timeline's brighter bars show which dates are real.

- [ ] **Step 2: Verify build**

Run: `cd web && npm run build`
Expected: PASS.

- [ ] **Step 3: Manual check note** (verified in Phase F live pass): toggle compare mode, pick two dates on the timeline, drag the slider — left shows "before", right shows "after".

- [ ] **Step 4: Commit**

```bash
git add web/src/components/map/BeforeAfterSwipe.tsx
git commit -m "feat(web): before/after water-extent swipe"
```

---

## Phase E — Analytics panels

### Task E1: KpiGrid

**Files:**
- Create: `web/src/components/panels/KpiGrid.tsx` (replace placeholder)

**Interfaces:**
- Consumes: `useUi` (selectedReservoir), `useStatus`, `useReservoirs`, `fx`, shadcn `Card`, `Badge`.
- Produces: `<KpiGrid/>` — a 2-col grid of KPI cards (fill, level/FRL, storage, surface area placeholder via status, release prob·lead) + a risk badge + staleness banner.

- [ ] **Step 1: Create the component**

```tsx
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { fx } from "@/lib/format";
import { useReservoirs, useStatus } from "@/lib/queries";
import { RISK_COLOR } from "@/lib/risk";
import { useUi } from "@/lib/store";

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <Card className="p-2">
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-[11px] text-muted-foreground">{label}</div>
    </Card>
  );
}

export function KpiGrid() {
  const { selectedReservoir } = useUi();
  const { data: status, isLoading } = useStatus(selectedReservoir);
  const { data: reservoirs = [] } = useReservoirs();
  const res = reservoirs.find((r) => r.reservoir_id === selectedReservoir) ?? null;
  if (isLoading) return <div className="h-24 animate-pulse rounded-md bg-secondary" />;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">Status as of {status?.as_of ?? "—"}</span>
        <Badge style={{ background: RISK_COLOR[status?.risk_level ?? "Low"] }}>{status?.risk_level ?? "—"}</Badge>
      </div>
      {status?.stale && (
        <div className="rounded-md border border-amber-500/50 bg-amber-500/10 px-2 py-1 text-xs text-amber-400">
          ⏳ Data {status.data_age_days}d old · serving last-known forecast-based risk
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        <Kpi label="fill" value={status ? `${fx(status.pct_filled)}%` : "…"} />
        <Kpi label="level / FRL"
             value={status?.level_m != null ? `${fx(status.level_m, 0)} / ${fx(res?.frl_m, 0)} m` : "…"} />
        <Kpi label="storage" value={status?.live_storage_bcm != null ? `${fx(status.live_storage_bcm, 2)} BCM` : "…"} />
        <Kpi label="release prob · lead"
             value={status?.release_probability != null
               ? `${fx(Number(status.release_probability) * 100, 0)}% · ${status.estimated_lead_time_days ?? "—"}d` : "…"} />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build** — `cd web && npm run build` → PASS.
- [ ] **Step 3: Commit** — `git add web/src/components/panels/KpiGrid.tsx && git commit -m "feat(web): KPI grid + staleness banner"`

---

### Task E2: TrendChart (adapt existing)

**Files:**
- Create: `web/src/components/panels/TrendChart.tsx` (replace placeholder)

**Interfaces:**
- Consumes: `useUi` (selectedReservoir), `useTimeseries`. Produces `<TrendChart/>` (no props — reads the store).

- [ ] **Step 1: Create the component** (dark-themed adaptation of the existing chart)

```tsx
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useTimeseries } from "@/lib/queries";
import { useUi } from "@/lib/store";

export function TrendChart() {
  const { selectedReservoir } = useUi();
  const { data: points = [] } = useTimeseries(selectedReservoir);
  if (points.length === 0) return <p className="p-4 text-sm text-muted-foreground">No history.</p>;
  const data = points.map((p) => ({
    date: p.date, fill: Number(p.pct_filled),
    normal: p.normal_storage_pct == null ? null : Number(p.normal_storage_pct),
  }));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -16 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#23364f" />
        <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#8ba0bd" }} minTickGap={40} />
        <YAxis domain={[0, 110]} tick={{ fontSize: 10, fill: "#8ba0bd" }} unit="%" />
        <Tooltip contentStyle={{ background: "#13233a", border: "1px solid #23364f", color: "#e8eef6" }} />
        <Legend />
        <Line type="monotone" dataKey="fill" stroke="#38bdf8" dot={false} name="fill %" />
        <Line type="monotone" dataKey="normal" stroke="#94a3b8" strokeDasharray="4 4" dot={false} name="seasonal normal" />
      </LineChart>
    </ResponsiveContainer>
  );
}
```

- [ ] **Step 2: Verify build** — PASS.
- [ ] **Step 3: Commit** — `git add web/src/components/panels/TrendChart.tsx && git commit -m "feat(web): trend chart (dark)"`

---

### Task E3: ForecastChart (adapt existing)

**Files:**
- Create: `web/src/components/panels/ForecastChart.tsx` (replace placeholder)

**Interfaces:**
- Consumes: `useUi` (selectedReservoir), `useForecast`. Produces `<ForecastChart/>` (no props).

- [ ] **Step 1: Create the component**

```tsx
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useForecast } from "@/lib/queries";
import { useUi } from "@/lib/store";

export function ForecastChart() {
  const { selectedReservoir } = useUi();
  const { data: forecast } = useForecast(selectedReservoir);
  if (!forecast || forecast.points.length === 0)
    return <p className="p-4 text-sm text-muted-foreground">No forecast available.</p>;
  const data = forecast.points.map((p) => ({
    date: p.horizon_date, predicted: Number(p.predicted_pct_filled),
    band: [Number(p.interval_low), Number(p.interval_high)],
  }));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -16 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#23364f" />
        <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#8ba0bd" }} />
        <YAxis domain={[0, 110]} tick={{ fontSize: 10, fill: "#8ba0bd" }} unit="%" />
        <Tooltip contentStyle={{ background: "#13233a", border: "1px solid #23364f", color: "#e8eef6" }} />
        <Area type="monotone" dataKey="band" stroke="none" fill="#38bdf8" fillOpacity={0.15} name="conformal interval" />
        <Line type="monotone" dataKey="predicted" stroke="#38bdf8" dot={false} name="forecast fill %" />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
```

- [ ] **Step 2: Verify build** — PASS.
- [ ] **Step 3: Commit** — `git add web/src/components/panels/ForecastChart.tsx && git commit -m "feat(web): forecast chart (dark)"`

---

### Task E4: ReleaseRiskPanel

**Files:**
- Create: `web/src/components/panels/ReleaseRiskPanel.tsx` (replace placeholder)

**Interfaces:**
- Consumes: `useUi`, `useStatus`, `useFleetRisk`, `fx`, `RISK_COLOR`. Produces `<ReleaseRiskPanel/>` — shows the selected reservoir's risk level, probability, lead time, and run timestamp, plus a short transparency note (ADR-0001).

- [ ] **Step 1: Create the component**

```tsx
import { fx } from "@/lib/format";
import { useFleetRisk, useStatus } from "@/lib/queries";
import { RISK_COLOR } from "@/lib/risk";
import { useUi } from "@/lib/store";

export function ReleaseRiskPanel() {
  const { selectedReservoir } = useUi();
  const { data: status } = useStatus(selectedReservoir);
  const { data: fleet = [] } = useFleetRisk();
  const fr = fleet.find((f) => f.reservoir_id === selectedReservoir) ?? null;
  const level = status?.risk_level ?? "Low";

  return (
    <div className="space-y-3 p-2 text-sm">
      <div className="flex items-center gap-2">
        <span className="h-4 w-4 rounded-sm" style={{ background: RISK_COLOR[level] }} />
        <span className="text-lg font-semibold">{level}</span>
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>Release probability<div className="text-base text-foreground">{status?.release_probability != null ? `${fx(Number(status.release_probability) * 100, 1)}%` : "—"}</div></div>
        <div>Estimated lead time<div className="text-base text-foreground">{status?.estimated_lead_time_days ?? "—"} d</div></div>
        <div>Last risk run<div className="text-base text-foreground">{fr?.run_timestamp?.slice(0, 10) ?? "—"}</div></div>
      </div>
      <p className="text-[11px] text-muted-foreground">
        Release-risk is a transparent layer over the forecast trajectory vs FRL/threshold bands net of the
        Normal-Storage rule curve (ADR-0001) — not a trained classifier.
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Verify build** — PASS.
- [ ] **Step 3: Commit** — `git add web/src/components/panels/ReleaseRiskPanel.tsx && git commit -m "feat(web): release-risk panel"`

---

### Task E5: AccuracyPanel

**Files:**
- Create: `web/src/components/panels/AccuracyPanel.tsx` (replace placeholder)

**Interfaces:**
- Consumes: `useAccuracy` (returns the `/accuracy` JSON, shape unknown → render as labelled key/values). Produces `<AccuracyPanel/>` with an explicit "historical backtest" label (ADR-0005).

- [ ] **Step 1: Inspect the `/accuracy` shape first**

Run (DB + API up): `curl -s http://localhost:18000/accuracy | head -c 400`
Use the observed keys to label the rendered rows. (The repo function is `repo.accuracy`; if it returns a flat dict of metrics, the generic renderer below suffices.)

- [ ] **Step 2: Create the component (generic, label-driven)**

```tsx
import { useAccuracy } from "@/lib/queries";

export function AccuracyPanel() {
  const { data } = useAccuracy();
  const entries = data && typeof data === "object" ? Object.entries(data as Record<string, unknown>) : [];
  return (
    <div className="space-y-2 p-2 text-sm">
      <div className="rounded-md border border-border bg-secondary/40 px-2 py-1 text-[11px] text-muted-foreground">
        Accuracy is a <b>historical backtest</b> (ADR-0005) — there is no live ground truth in production.
      </div>
      {entries.length === 0 ? (
        <p className="text-muted-foreground">No accuracy metrics available.</p>
      ) : (
        <dl className="grid grid-cols-2 gap-1 text-xs">
          {entries.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted-foreground">{k}</dt>
              <dd className="text-foreground">{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify build** — PASS.
- [ ] **Step 4: Commit** — `git add web/src/components/panels/AccuracyPanel.tsx && git commit -m "feat(web): accuracy panel (backtest-labelled)"`

---

### Task E6: DataTable + CSV download

**Files:**
- Create: `web/src/components/panels/DataTable.tsx` (replace placeholder)

**Interfaces:**
- Consumes: `useUi`, `useTimeseries`, `useAcquisitions`, shadcn `Button`. Produces `<DataTable/>` — a scrollable table of the timeseries with a "Download CSV" button (client-side blob).

- [ ] **Step 1: Create the component**

```tsx
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { fx } from "@/lib/format";
import { useTimeseries } from "@/lib/queries";
import { useUi } from "@/lib/store";

export function DataTable() {
  const { selectedReservoir } = useUi();
  const { data: rows = [] } = useTimeseries(selectedReservoir);

  const downloadCsv = () => {
    const header = "date,pct_filled,level_m,live_storage_bcm,normal_storage_pct";
    const body = rows.map((r) =>
      [r.date, r.pct_filled, r.level_m ?? "", r.live_storage_bcm ?? "", r.normal_storage_pct ?? ""].join(","),
    );
    const blob = new Blob([[header, ...body].join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${selectedReservoir}-timeseries.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <Button size="sm" variant="secondary" onClick={downloadCsv} disabled={rows.length === 0}>Download CSV</Button>
      </div>
      <ScrollArea className="h-64 rounded-md border border-border">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-secondary">
            <tr><th className="p-1 text-left">date</th><th className="p-1">fill%</th><th className="p-1">level m</th><th className="p-1">BCM</th><th className="p-1">normal%</th></tr>
          </thead>
          <tbody>
            {rows.slice().reverse().map((r) => (
              <tr key={r.date} className="border-t border-border">
                <td className="p-1">{r.date}</td><td className="p-1 text-center">{fx(r.pct_filled)}</td>
                <td className="p-1 text-center">{fx(r.level_m, 0)}</td><td className="p-1 text-center">{fx(r.live_storage_bcm, 2)}</td>
                <td className="p-1 text-center">{fx(r.normal_storage_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollArea>
    </div>
  );
}
```

- [ ] **Step 2: Verify build** — PASS.
- [ ] **Step 3: Commit** — `git add web/src/components/panels/DataTable.tsx && git commit -m "feat(web): data table + CSV download"`

---

## Phase F — Cleanup, optional tests, live verification

### Task F1: Remove the old frontend, final build

**Files:**
- Delete: `web/src/styles.css`, `web/src/components/ReservoirMap.tsx`, `web/src/api.ts`, `web/src/components/ForecastChart.tsx`, `web/src/components/TrendChart.tsx` (the old top-level copies — the panels now live under `components/panels/`).

**Interfaces:** none new — this removes dead code.

- [ ] **Step 1: Grep for stale imports**

Run: `cd web && grep -rn "styles.css\|components/ReservoirMap\|\"./api\"\|from \"../types\"" src || echo "clean"`
Expected: no references outside the files being deleted. Fix any stragglers to use `@/lib/api` / `@/types`.

- [ ] **Step 2: Delete the dead files**

Run:
```bash
cd web && git rm src/styles.css src/components/ReservoirMap.tsx src/api.ts \
  src/components/ForecastChart.tsx src/components/TrendChart.tsx
```

- [ ] **Step 3: Final build + lint-ish check**

Run: `cd web && npm run build`
Expected: PASS (no unused-locals errors; tsconfig has `noUnusedLocals`).

- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(web): remove legacy dashboard files"
```

---

### Task F2 (optional but recommended): Vitest + store test

**Files:**
- Modify: `web/package.json` (devDeps + `test` script)
- Create: `web/vitest.config.ts`, `web/src/lib/store.test.ts`

**Interfaces:** Produces a `npm test` gate covering the store reducer logic (the one piece of non-trivial frontend logic).

- [ ] **Step 1: Install** — `cd web && npm install -D vitest @testing-library/react jsdom`
- [ ] **Step 2: Create `web/vitest.config.ts`**

```ts
import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  test: { environment: "jsdom" },
});
```

- [ ] **Step 3: Write the test**

```ts
import { beforeEach, describe, expect, it } from "vitest";
import { useUi } from "@/lib/store";

describe("ui store", () => {
  beforeEach(() => useUi.setState({ selectedReservoir: null, activeDate: "x", compare: { before: "a", after: "b" }, compareMode: false }));

  it("select() resets active date and compare pins", () => {
    useUi.getState().select("pong");
    const s = useUi.getState();
    expect(s.selectedReservoir).toBe("pong");
    expect(s.activeDate).toBeNull();
    expect(s.compare).toEqual({ before: null, after: null });
  });

  it("toggleLayer flips a single layer", () => {
    const before = useUi.getState().layers.catchment;
    useUi.getState().toggleLayer("catchment");
    expect(useUi.getState().layers.catchment).toBe(!before);
  });
});
```

- [ ] **Step 4: Add script + run** — add `"test": "vitest run"` to `web/package.json` scripts; run `cd web && npm test`. Expected: PASS.
- [ ] **Step 5: Commit** — `git add web/package.json web/package-lock.json web/vitest.config.ts web/src/lib/store.test.ts && git commit -m "test(web): vitest + ui store tests"`

---

### Task F3: Live verification pass

**Interfaces:** none — manual confirmation the whole console works against the live stack.

- [ ] **Step 1: Bring the stack up**

Run (Docker running): from repo root, ensure Postgres is up (`docker compose -f infra/compose/docker-compose.yml up -d postgres`), migrate + bootstrap if needed (`uv run python scripts/bootstrap.py` with the `DATABASE_URL_*` envs), start the API (`uv run uvicorn api.main:app --port 18000`), and `cd web && npm run dev`.

- [ ] **Step 2: Walk the checklist** (open http://localhost:5173)
  - Topbar fleet chips switch the selected reservoir; freshness shows stale (data is >14d old in the fixture).
  - Left sidebar: select each reservoir; toggle each layer and confirm the map overlay appears/disappears.
  - Bottom timeline: scrub dates; the water overlay updates; the "derived" badge shows on non-latest dates and disappears on the latest (real) date.
  - Imagery → Compare: pick a before (click) and after (shift-click) date; drag the swipe handle; both labels show date + area.
  - Drawer tabs: Trend, Forecast (conformal band), Risk (level + note), Accuracy (backtest label), Data (table + CSV download actually downloads a file).

- [ ] **Step 3: Final commit (if any tweaks)** — commit any fixes found during the walk-through with a clear message.

---

## Self-review

**Spec coverage:**
- Left control sidebar (reservoir, layers, imagery/before-after) → C2. ✓
- Toggle imagery / layers → C2 + D1 gating. ✓
- Before/after comparison → D3 (+ A2 derived masks). ✓
- Timeseries of all images to recent date → C3 timeline (+ A1 acquisitions). ✓
- EO-browser canvas layout (topbar/sidebar/map/drawer/timeline) → C1, C2, C3, C4, D1. ✓
- Tailwind + shadcn/ui → B1, B2. ✓
- TanStack Query + Zustand → B2, B3. ✓
- Server-side derived-mask synthesis, swap-to-real seam → A2. ✓
- Derived badge + staleness banner (honesty) → D2, E1. ✓
- Analyst panels (KPI, trend, forecast, risk, accuracy, data+CSV) → E1–E6. ✓
- Build-clean gate + live smoke → every task + F1/F3; optional Vitest → F2. ✓

**Placeholder scan:** No "TBD"/"implement later". The intentional thin component stubs in C1/C4/D1 are explicitly created and then replaced in named later tasks — flagged inline, not vague. The one corrected mistake (`toggleCompare` signature) is called out with the fix in B3.

**Type consistency:** `Acquisition`, `WaterExtentFeature`, `UiState`, `api.*`, and the query-hook names are defined once in B3 and used unchanged in C/D/E. The backend `acquisitions`/`water_extent_by_date` repo signatures match their routes and tests. `RISK_COLOR` moves to `lib/risk.ts` (removed from `types.ts`) in B3-Step1/2 and every consumer imports from `@/lib/risk`.
