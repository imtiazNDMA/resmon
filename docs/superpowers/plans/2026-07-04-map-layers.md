# Map Layers (Catchment + Water Extent) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Toggleable catchment and latest-water-extent overlays on `MapView`, with an honest date/staleness chip and a C5 provenance fix on the water-extent serving path.

**Architecture:** Two self-contained react-leaflet `GeoJSON` layer components fed by new react-query hooks over the existing `/geojson/catchment` and `/geojson/water-extent` endpoints; layer visibility is two booleans in the zustand store toggled by a custom chips control. Scrub/staleness rules live in a pure, unit-tested module. One backend WHERE-clause fix.

**Tech Stack:** React 18 + TypeScript + react-leaflet 4 + zustand 5 + @tanstack/react-query 5 + vitest 4 (frontend); FastAPI + SQLAlchemy + PostGIS + pytest (backend).

**Spec:** `docs/superpowers/specs/2026-07-04-map-layers-design.md` (approved 2026-07-04).

## Global Constraints

- Layer toggles default **on**; catchment renders for the **selected reservoir only**.
- The extent polygon may only show when the timeline sits on the **latest acquisition date** (from `useAcquisitions`, i.e. the last timeline entry — NOT the mask's own date, which can be older when newer observations lack masks).
- The date chip always shows the mask's `acquisition_date`; stale means **age > 14 days** (strictly greater — mirrors `data_staleness_threshold_days` default in `core/src/core/config.py:22` and the `>` comparison in `api/src/api/repositories.py:110`), computed on the **IST calendar** (`Asia/Kolkata`, D9).
- Colors: catchment `#d9a45b` dashed / fill 0.04; water extent `#39d5c8` solid / fill 0.25; stale extent outline opacity 0.5. AOI layer unchanged.
- Layers degrade independently: query error or missing feature ⇒ layer renders nothing, its chip disables. No `Promise.all`, no global error state.
- Frontend commands run in `web/` (`npm run test` = `vitest run`, `npm run build` = `tsc --noEmit && vite build`). Backend commands run at repo root with `uv run`. Integration tests need the dev Postgres from `.env` (`POSTGRES_HOST_PORT=55432`); they skip if it's down, so make sure `docker compose up -d db` (or the full dev stack) is running.
- Commit after every task. Never use `--no-verify`.

---

### Task 1: Backend C5 provenance fix in `water_extent_features`

The serving path for `/geojson/water-extent` filters only on `water_mask_geom IS NOT NULL`. A synthetic-provenance row (C5: `scene_ids = ARRAY['synthetic']`, real extractor name) that carries a mask geometry would be served as the "latest" extent. Add the `_REAL_OBS` filter.

**Files:**
- Modify: `api/src/api/repositories.py:303` (the `water_extent_features` WHERE clause)
- Test: `tests/integration/test_api.py` (append after `test_synthetic_rows_never_mint_tiles_or_freshen_staleness`, ~line 142)

**Interfaces:**
- Consumes: existing `_REAL_OBS` SQL fragment (`api/src/api/repositories.py:28`). Its column references are unqualified (`extraction_method`, `scene_ids`) but resolve unambiguously to the `observation o` alias — `reservoir` has no columns with those names.
- Produces: `/geojson/water-extent` never serves synthetic masks. Frontend tasks rely on `properties.acquisition_date` being a real acquisition's ISO date string.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_api.py` (it already imports `pytest` and `text` at the top):

```python
@pytest.fixture
def seeded_mask_rows(client, session):
    """One real observation WITH a mask geometry plus a NEWER synthetic-provenance row
    that also has a mask (C5) — /geojson/water-extent must serve the real one."""
    for d, area, sid in (
        ("2020-01-05", 120.5, "S1A_TEST_0001"),
        ("2026-01-01", 999.0, "synthetic"),
    ):
        session.execute(
            text(
                """
                INSERT INTO observation
                    (reservoir_id, acquisition_date, surface_area, area_confidence,
                     water_mask_ref, extraction_method, extraction_version, scene_ids,
                     orbit_relative, pass_direction, aoi_version, layover_shadow_fraction,
                     processing_params, water_mask_geom)
                VALUES
                    ('gobind_sagar', :d, :area, 0.9, :ref, 'otsu_vh', 'v1',
                     ARRAY[:sid], 27, 'ASC', 'v1', 0, CAST('{}' AS jsonb),
                     ST_Multi(ST_GeomFromText(
                       'POLYGON((76.4 31.4, 76.5 31.4, 76.5 31.5, 76.4 31.5, 76.4 31.4))', 4326)))
                ON CONFLICT (reservoir_id, acquisition_date) DO UPDATE SET
                    surface_area = EXCLUDED.surface_area,
                    extraction_method = EXCLUDED.extraction_method,
                    scene_ids = EXCLUDED.scene_ids,
                    water_mask_geom = EXCLUDED.water_mask_geom
                """
            ),
            {"d": d, "area": area, "ref": f"backfill://{sid}", "sid": sid},
        )


def test_water_extent_excludes_synthetic_masks(client, seeded_mask_rows):
    # C5: the synthetic 2026 row has a mask AND a newer date — if the provenance
    # filter is missing, DISTINCT ON picks it as the "latest" extent.
    gj = client.get("/geojson/water-extent").json()
    gs = [f for f in gj["features"] if f["properties"]["reservoir_id"] == "gobind_sagar"]
    assert len(gs) == 1
    assert gs[0]["properties"]["acquisition_date"] == "2020-01-05"
    assert gs[0]["geometry"]["type"] in ("Polygon", "MultiPolygon")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_api.py::test_water_extent_excludes_synthetic_masks -v`
Expected: FAIL — the feature's `acquisition_date` is `"2026-01-01"` (synthetic row wins `DISTINCT ON ... ORDER BY acquisition_date DESC`).
(If it reports SKIPPED, the dev DB isn't up: `docker compose up -d db`, then re-run.)

- [ ] **Step 3: Apply the fix**

In `api/src/api/repositories.py`, `water_extent_features`, change the WHERE line:

```python
            WHERE o.water_mask_geom IS NOT NULL AND {_REAL_OBS}
```

(The f-string already interpolates `_bounded_geojson`; `{_REAL_OBS}` interpolates the same way.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_api.py -v`
Expected: all PASS (the new test plus the existing geojson/serving-path tests — confirms no regression in `test_geojson_layers`).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format api/src/api/repositories.py tests/integration/test_api.py
uv run ruff check api/src/api/repositories.py tests/integration/test_api.py
git add api/src/api/repositories.py tests/integration/test_api.py
git commit -m "fix(api): apply the C5 _REAL_OBS filter to the water-extent layer"
```

---

### Task 2: Frontend data plumbing — types, API client, query hooks

**Files:**
- Modify: `web/src/types.ts` (append after `AoiProperties`, ~line 58)
- Modify: `web/src/lib/api.ts` (extend the `api` object, ~line 40)
- Modify: `web/src/lib/queries.ts` (append after `useAoi`, ~line 8)

**Interfaces:**
- Consumes: `GeoFC<P>` generic from `types.ts`, `getJson` helper in `api.ts`.
- Produces (later tasks import these exact names):
  - `CatchmentProperties { reservoir_id: string; name: string; version: string | null }`
  - `WaterExtentProperties { reservoir_id: string; name: string; surface_area_km2: number; acquisition_date: string }`
  - `api.catchment(s?: AbortSignal): Promise<GeoFC<CatchmentProperties>>`
  - `api.waterExtent(s?: AbortSignal): Promise<GeoFC<WaterExtentProperties>>`
  - `useCatchment(): UseQueryResult<GeoFC<CatchmentProperties>>`
  - `useWaterExtent(): UseQueryResult<GeoFC<WaterExtentProperties>>`

- [ ] **Step 1: Add the property types**

Append to `web/src/types.ts`:

```ts
/** Properties on `/geojson/catchment` features (HydroSHEDS HydroBASINS). */
export interface CatchmentProperties {
  reservoir_id: string;
  name: string;
  version: string | null;
}

/** Properties on `/geojson/water-extent` features (latest real SAR mask per reservoir). */
export interface WaterExtentProperties {
  reservoir_id: string;
  name: string;
  surface_area_km2: number;
  acquisition_date: string;
}
```

(These mirror `CatchmentProperties`/`WaterExtentProperties` in `api/src/api/schemas.py:135-145`; pydantic serialises `date` as an ISO string.)

- [ ] **Step 2: Add the client functions**

In `web/src/lib/api.ts`, add `CatchmentProperties, WaterExtentProperties` to the type import, then add to the `api` object after `aoi`:

```ts
  catchment: (s?: AbortSignal) => getJson<GeoFC<CatchmentProperties>>("/geojson/catchment", s),
  waterExtent: (s?: AbortSignal) =>
    getJson<GeoFC<WaterExtentProperties>>("/geojson/water-extent", s),
```

- [ ] **Step 3: Add the query hooks**

In `web/src/lib/queries.ts`, after `useAoi`:

```ts
export const useCatchment = () =>
  useQuery({
    queryKey: ["catchment"],
    queryFn: ({ signal }) => api.catchment(signal),
    staleTime: Infinity, // catchment geometry is static, same contract as useAoi
  });

export const useWaterExtent = () =>
  useQuery({
    queryKey: ["waterExtent"],
    queryFn: ({ signal }) => api.waterExtent(signal),
    staleTime: 10 * 60_000, // a new mask lands at most per-scene; matches acquisitions
  });
```

- [ ] **Step 4: Typecheck**

Run (in `web/`): `npm run build`
Expected: PASS (`tsc --noEmit` clean, vite build succeeds).

- [ ] **Step 5: Commit**

```bash
git add web/src/types.ts web/src/lib/api.ts web/src/lib/queries.ts
git commit -m "feat(web): API client + query hooks for catchment and water-extent layers"
```

---

### Task 3: Pure visibility/staleness module `extentVisibility.ts` (TDD)

**Files:**
- Create: `web/src/lib/extentVisibility.ts`
- Test: `web/src/lib/extentVisibility.test.ts`

**Interfaces:**
- Consumes: nothing (pure).
- Produces (Tasks 5–7 import these exact names):
  - `isExtentVisible(activeDate: string | null, latestAcquisitionDate: string | null | undefined): boolean`
  - `isExtentStale(acquisitionDate: string, today?: string): boolean`
  - `formatDayMonth(isoDate: string): string` — `"2026-06-12"` → `"12 Jun"`
  - `STALENESS_THRESHOLD_DAYS = 14`

- [ ] **Step 1: Write the failing tests**

Create `web/src/lib/extentVisibility.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  extentAgeDays,
  formatDayMonth,
  isExtentStale,
  isExtentVisible,
} from "./extentVisibility";

describe("isExtentVisible (extent only shows at the latest timeline date)", () => {
  it("visible when the timeline sits on the latest acquisition", () => {
    expect(isExtentVisible("2026-06-12", "2026-06-12")).toBe(true);
  });
  it("hidden when scrubbed back", () => {
    expect(isExtentVisible("2026-05-01", "2026-06-12")).toBe(false);
  });
  it("hidden while the timeline has no date yet", () => {
    expect(isExtentVisible(null, "2026-06-12")).toBe(false);
  });
  it("hidden when there are no acquisitions", () => {
    expect(isExtentVisible("2026-06-12", null)).toBe(false);
    expect(isExtentVisible("2026-06-12", undefined)).toBe(false);
  });
  it("tolerates datetime-formatted date strings", () => {
    expect(isExtentVisible("2026-06-12", "2026-06-12T00:00:00")).toBe(true);
  });
});

describe("staleness (age > 14 days, mirrors data_staleness_threshold_days)", () => {
  it("boundary: 13 and 14 days old are fresh, 15 is stale", () => {
    expect(isExtentStale("2026-06-21", "2026-07-04")).toBe(false); // 13d
    expect(isExtentStale("2026-06-20", "2026-07-04")).toBe(false); // 14d
    expect(isExtentStale("2026-06-19", "2026-07-04")).toBe(true); // 15d
  });
  it("extentAgeDays counts calendar days", () => {
    expect(extentAgeDays("2026-07-01", "2026-07-04")).toBe(3);
    expect(extentAgeDays("2026-07-04", "2026-07-04")).toBe(0);
  });
});

describe("formatDayMonth", () => {
  it("renders the chip date", () => {
    expect(formatDayMonth("2026-06-12")).toBe("12 Jun");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (in `web/`): `npm run test`
Expected: FAIL — `Cannot find module './extentVisibility'` (or equivalent resolve error). `store.test.ts` still passes.

- [ ] **Step 3: Write the implementation**

Create `web/src/lib/extentVisibility.ts`:

```ts
/** Scrub/staleness rules for the water-extent overlay, kept pure so the
 *  date-string contracts are testable without mounting Leaflet. */

const DAY_MS = 86_400_000;

/** Mirrors `data_staleness_threshold_days` (core/src/core/config.py, NFR-REL-6/D8). */
export const STALENESS_THRESHOLD_DAYS = 14;

// Data dates live on the IST calendar (D9) — age must not use the browser's zone.
const IST_DATE = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" });

/** YYYY-MM-DD "today" on the IST calendar. */
export function istToday(): string {
  return IST_DATE.format(new Date());
}

function toUtcMs(isoDate: string): number {
  return Date.parse(`${isoDate.slice(0, 10)}T00:00:00Z`);
}

/** The extent polygon may only show when the timeline sits on the latest
 *  acquisition — scrubbed back, the outline would contradict older imagery. */
export function isExtentVisible(
  activeDate: string | null,
  latestAcquisitionDate: string | null | undefined,
): boolean {
  if (!activeDate || !latestAcquisitionDate) return false;
  return activeDate.slice(0, 10) === latestAcquisitionDate.slice(0, 10);
}

export function extentAgeDays(acquisitionDate: string, today: string = istToday()): number {
  return Math.round((toUtcMs(today) - toUtcMs(acquisitionDate)) / DAY_MS);
}

export function isExtentStale(acquisitionDate: string, today: string = istToday()): boolean {
  return extentAgeDays(acquisitionDate, today) > STALENESS_THRESHOLD_DAYS;
}

/** "2026-06-12" -> "12 Jun" for the extent date chip. */
export function formatDayMonth(isoDate: string): string {
  return new Date(toUtcMs(isoDate)).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (in `web/`): `npm run test`
Expected: PASS (all files).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/extentVisibility.ts web/src/lib/extentVisibility.test.ts
git commit -m "feat(web): pure scrub-visibility and IST staleness rules for the extent layer"
```

---

### Task 4: Store layer toggles (TDD)

**Files:**
- Modify: `web/src/lib/store.ts`
- Test: `web/src/lib/store.test.ts` (append a test)

**Interfaces:**
- Consumes: existing zustand store shape.
- Produces (Tasks 5–7 read these exact names): `showCatchment: boolean`, `showWaterExtent: boolean` (both default `true`), `toggleLayer(layer: "catchment" | "waterExtent"): void`.

- [ ] **Step 1: Write the failing test**

Append inside the existing `describe` block in `web/src/lib/store.test.ts`:

```ts
  it("layer toggles default on and flip independently", () => {
    expect(s().showCatchment).toBe(true);
    expect(s().showWaterExtent).toBe(true);
    s().toggleLayer("catchment");
    expect(s().showCatchment).toBe(false);
    expect(s().showWaterExtent).toBe(true); // independent
    s().toggleLayer("catchment");
    expect(s().showCatchment).toBe(true);
    s().toggleLayer("waterExtent");
    expect(s().showWaterExtent).toBe(false);
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run (in `web/`): `npm run test`
Expected: FAIL — `s().toggleLayer is not a function` (also a TS error; vitest still reports the failure).

- [ ] **Step 3: Implement the toggles**

In `web/src/lib/store.ts`, add to the `AppState` interface:

```ts
  showCatchment: boolean;
  showWaterExtent: boolean;
  toggleLayer: (layer: "catchment" | "waterExtent") => void;
```

and to the store initialiser (after `playing: false,`):

```ts
  showCatchment: true,
  showWaterExtent: true,
  toggleLayer: (layer) =>
    set(
      layer === "catchment"
        ? { showCatchment: !get().showCatchment }
        : { showWaterExtent: !get().showWaterExtent },
    ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run (in `web/`): `npm run test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/store.ts web/src/lib/store.test.ts
git commit -m "feat(web): layer-visibility toggles in the app store (default on)"
```

---

### Task 5: `CatchmentLayer` component + MapView wiring

**Files:**
- Create: `web/src/components/stage/CatchmentLayer.tsx`
- Modify: `web/src/components/stage/MapView.tsx`

**Interfaces:**
- Consumes: `useCatchment` (Task 2), `showCatchment` (Task 4), `useAppStore.selected`.
- Produces: `<CatchmentLayer />` — self-gating (renders `null` unless a reservoir is selected, the toggle is on, and its feature exists). Must be mounted **inside** `MapContainer`.

- [ ] **Step 1: Write the component**

Create `web/src/components/stage/CatchmentLayer.tsx`:

```tsx
import { GeoJSON } from "react-leaflet";
import { useCatchment } from "../../lib/queries";
import { useAppStore } from "../../lib/store";

/** Upstream catchment (HydroBASINS) for the selected reservoir. Dashed sand
 *  outline so it reads as a terrain boundary, not water. Degrades to nothing
 *  on query error or missing feature — never blocks the other layers. */
export default function CatchmentLayer() {
  const selected = useAppStore((s) => s.selected);
  const show = useAppStore((s) => s.showCatchment);
  const { data } = useCatchment();
  if (!selected || !show || !data) return null;
  const f = data.features.find((x) => x.properties.reservoir_id === selected);
  if (!f) return null;
  return (
    <GeoJSON
      key={`catchment-${selected}`}
      data={f}
      style={{ color: "#d9a45b", weight: 1.5, dashArray: "6 4", fillOpacity: 0.04 }}
    />
  );
}
```

(The `key` remount-on-switch trick matches the existing AOI layer in `MapView.tsx:50`.)

- [ ] **Step 2: Mount it in MapView**

In `web/src/components/stage/MapView.tsx`: add `import CatchmentLayer from "./CatchmentLayer";` and render it inside `MapContainer`, directly after the `{aoi && (...)}` block:

```tsx
        <CatchmentLayer />
```

- [ ] **Step 3: Typecheck + tests**

Run (in `web/`): `npm run build` then `npm run test`
Expected: both PASS.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/stage/CatchmentLayer.tsx web/src/components/stage/MapView.tsx
git commit -m "feat(web): catchment overlay for the selected reservoir"
```

---

### Task 6: `WaterExtentLayer` component

**Files:**
- Create: `web/src/components/stage/WaterExtentLayer.tsx`
- Modify: `web/src/components/stage/MapView.tsx`

**Interfaces:**
- Consumes: `useWaterExtent`, `useAcquisitions` (existing), `showWaterExtent`, `activeDate`, `isExtentVisible`, `isExtentStale` (Task 3).
- Produces: `<WaterExtentLayer />` — self-gating, polygon only (the date chip is Task 7's `LayerChips`). Must be mounted **inside** `MapContainer`.

- [ ] **Step 1: Write the component**

Create `web/src/components/stage/WaterExtentLayer.tsx`:

```tsx
import { GeoJSON } from "react-leaflet";
import { isExtentStale, isExtentVisible } from "../../lib/extentVisibility";
import { useAcquisitions, useWaterExtent } from "../../lib/queries";
import { useAppStore } from "../../lib/store";

/** Latest vectorised SAR water mask for the selected reservoir. Drawn only when
 *  the timeline sits on the latest acquisition, so the outline never contradicts
 *  older imagery underneath (spec: scrub auto-hide). Stale masks (>14d IST) dim. */
export default function WaterExtentLayer() {
  const selected = useAppStore((s) => s.selected);
  const show = useAppStore((s) => s.showWaterExtent);
  const activeDate = useAppStore((s) => s.activeDate);
  const { data } = useWaterExtent();
  const { data: acqs } = useAcquisitions(selected);
  if (!selected || !show || !data) return null;
  const f = data.features.find((x) => x.properties.reservoir_id === selected);
  if (!f) return null;
  const latest = acqs?.length ? acqs[acqs.length - 1]!.date : null;
  if (!isExtentVisible(activeDate, latest)) return null;
  const stale = isExtentStale(f.properties.acquisition_date);
  return (
    <GeoJSON
      key={`extent-${selected}-${f.properties.acquisition_date}`}
      data={f}
      style={{ color: "#39d5c8", weight: 2, opacity: stale ? 0.5 : 1, fillOpacity: 0.25 }}
    />
  );
}
```

- [ ] **Step 2: Mount it in MapView**

In `web/src/components/stage/MapView.tsx`: add `import WaterExtentLayer from "./WaterExtentLayer";` and render it inside `MapContainer`, after `<CatchmentLayer />` but **before** the `SarTileLayer` line so markers/tiles stay on top of fills in the overlay pane:

```tsx
        <WaterExtentLayer />
```

- [ ] **Step 3: Typecheck + tests**

Run (in `web/`): `npm run build` then `npm run test`
Expected: both PASS.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/stage/WaterExtentLayer.tsx web/src/components/stage/MapView.tsx
git commit -m "feat(web): latest water-extent overlay with scrub auto-hide and stale dimming"
```

---

### Task 7: `LayerChips` control, date chip, CSS

**Files:**
- Create: `web/src/components/stage/LayerChips.tsx`
- Modify: `web/src/components/stage/MapView.tsx`
- Modify: `web/src/styles.css` (new rules + nudge `.imagery-chip` down)

**Interfaces:**
- Consumes: `useCatchment`, `useWaterExtent`, store toggles (Task 4), `formatDayMonth`, `isExtentStale` (Task 3).
- Produces: `<LayerChips />` — plain absolutely-positioned div; mounted in `.mapview` **outside** `MapContainer` (same pattern as `AreaMeter`). Self-gates on `selected`.

- [ ] **Step 1: Write the component**

Create `web/src/components/stage/LayerChips.tsx`:

```tsx
import { formatDayMonth, isExtentStale } from "../../lib/extentVisibility";
import { useCatchment, useWaterExtent } from "../../lib/queries";
import { useAppStore } from "../../lib/store";

/** Top-right layer toggles + the always-honest extent date chip. A chip disables
 *  (rather than erroring) when its layer has no data for the selected reservoir. */
export default function LayerChips() {
  const selected = useAppStore((s) => s.selected);
  const showCatchment = useAppStore((s) => s.showCatchment);
  const showWaterExtent = useAppStore((s) => s.showWaterExtent);
  const toggleLayer = useAppStore((s) => s.toggleLayer);
  const { data: catchment } = useCatchment();
  const { data: extent } = useWaterExtent();
  if (!selected) return null;
  const hasCatchment = !!catchment?.features.some(
    (f) => f.properties.reservoir_id === selected,
  );
  const extentFeature = extent?.features.find(
    (f) => f.properties.reservoir_id === selected,
  );
  const stale = extentFeature ? isExtentStale(extentFeature.properties.acquisition_date) : false;
  return (
    <div className="layer-chips">
      <button
        className={`layer-chip ${showCatchment ? "on" : ""}`}
        disabled={!hasCatchment}
        onClick={() => toggleLayer("catchment")}
      >
        Catchment
      </button>
      <button
        className={`layer-chip ${showWaterExtent ? "on" : ""}`}
        disabled={!extentFeature}
        onClick={() => toggleLayer("waterExtent")}
      >
        Water extent
      </button>
      {showWaterExtent && extentFeature && (
        <span className={`extent-date-chip ${stale ? "stale" : ""}`}>
          extent · {formatDayMonth(extentFeature.properties.acquisition_date)}
        </span>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Mount it in MapView**

In `web/src/components/stage/MapView.tsx`: add `import LayerChips from "./LayerChips";` and render it in the `.mapview` div **after** `</MapContainer>`, next to the `AreaMeter` line:

```tsx
      <LayerChips />
```

- [ ] **Step 3: Add the CSS**

In `web/src/styles.css`, first change the existing `.imagery-chip` rule's `top: 12px` to `top: 48px` (the warning chip drops below the new controls — it only appears on SAR-tile errors). Then add after that rule:

```css
/* ---- Layer chips (map overlay toggles + extent date) ---- */
.layer-chips {
  position: absolute; top: 12px; right: 12px; z-index: 1100;
  display: flex; gap: 8px; align-items: center;
}
.layer-chip {
  background: rgba(21,27,35,.9); border: 1px solid var(--line); color: var(--muted);
  font-size: 11px; padding: 6px 10px; border-radius: 16px; cursor: pointer;
  font-family: var(--font);
}
.layer-chip.on { border-color: var(--water); color: var(--text); }
.layer-chip:disabled { opacity: .4; cursor: default; }
.extent-date-chip {
  background: rgba(21,27,35,.9); border: 1px solid var(--line); color: var(--muted);
  font-size: 11px; padding: 6px 10px; border-radius: 16px; font-family: var(--mono);
}
.extent-date-chip.stale { border-color: var(--warn); color: var(--warn); }
```

- [ ] **Step 4: Full frontend verification**

Run (in `web/`): `npm run test` then `npm run build`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/stage/LayerChips.tsx web/src/components/stage/MapView.tsx web/src/styles.css
git commit -m "feat(web): layer toggle chips with honest extent-date/staleness chip"
```

---

### Task 8: End-to-end verification (browser smoke)

**Files:** none created — verification only.

**Interfaces:**
- Consumes: the full dev stack (`docker compose up -d` per `.env` pins: API on `localhost:18000`, `npm run dev` in `web/` for vite on its default port with the `/api` proxy).

- [ ] **Step 1: Run the full local gate**

```bash
uv run ruff format --check . && uv run ruff check . && uv run mypy .
uv run pytest
cd web && npm run test && npm run build
```
Expected: all clean/PASS (integration tests need the dev DB up).

- [ ] **Step 2: Browser smoke checklist**

Start the stack and open the app. Verify each:

1. Select a reservoir → camera flies in, **catchment appears** (dashed sand outline), both chips lit, extent date chip shows a real date.
2. **Water extent** (cyan fill) visible when the timeline is at its latest date.
3. Scrub the timeline back → extent polygon **disappears**; date chip stays. Scrub to latest → it returns.
4. Toggle each chip off/on → layer hides/shows immediately; toggles are independent.
5. Switch reservoirs → overlays swap cleanly, no stale geometry from the previous reservoir.
6. If the latest mask is >14 days old (likely — the single populate_geometry mask), the date chip is **amber** and the extent outline dimmed. If not reproducible with live data, temporarily hardcode `today` in `isExtentStale`'s call site to verify, then revert.
7. Stop the API container → reload → base map, markers and SAR imagery flow still work; layer chips disable; no error banner. Restart the API.

- [ ] **Step 3: Report**

No commit. Report smoke results (with any deviations) before declaring the sub-project done.

---

## Self-review notes

- Spec coverage: decisions 1–5 → Tasks 4/7 (toggles default on), 5 (selected-only catchment), 3/6 (scrub auto-hide), 3/7 (date chip + stale tint, IST, >14d), backend rider → Task 1. Styling table → Tasks 5/6/7. Error-independence → self-gating components, no shared load state, smoke step 7.
- Refinement over the spec (approved intent, precise mechanics): "latest acquisition date" for the auto-hide rule is the **timeline's** latest entry, not the mask's own `acquisition_date` — the newest observations (backfill) have no masks, so equality against the mask date could never be true. The chip still shows the mask's own date.
- Type consistency: `toggleLayer("catchment" | "waterExtent")` (Tasks 4, 7); `isExtentVisible/isExtentStale/formatDayMonth` signatures identical in Tasks 3, 6, 7; `CatchmentProperties.version: string | null` matches `schemas.py`.
