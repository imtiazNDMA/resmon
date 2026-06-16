# 07 — Frontend Dashboard Implementation Plan

**Scope:** Web dashboard for the Reservoir Monitoring & Analytics Platform (disaster-management / flood-release early warning).
**Owner:** Frontend.
**Status:** Plan for review.
**Last updated:** 2026-06-16.
**Implements:** FR-UI-1..7 (§5.6), AC-6, AC-11 (UI side), NFR-UX-1 (§7.7), NFR-TIME-2/3 (freshness + p95), NFR-SEC-1 (RBAC gating, UI side).

> Planning document only. No application code is produced here. The single new artefact is this file.

---

## 1. Scope & owned requirements

The frontend `web/` app is the entire user-facing serving surface. It consumes the FastAPI REST/JSON + GeoJSON API (read-only for most roles; admin write for management). It owns:

| Req | What the frontend delivers |
| --- | --- |
| **FR-UI-1** | Real-time Leaflet map: reservoir markers colour-coded by **release-risk level**, AOI polygon overlay, current water-extent GeoJSON overlay, catchment overlay. |
| **FR-UI-2** | Analytics dashboard: KPI cards (fill %, volume BCM, level vs FRL, surface area) + trend charts (current-yr / last-yr / normal). |
| **FR-UI-3** | Forecast charts (1–14 day, prediction intervals) + **release-risk outlook panel** (level, probability, lead time, contributing factors); risk colour on map markers. |
| **FR-UI-4** | Estimate-vs-ground-truth / accuracy view (analyst trust). |
| **FR-UI-5** | Reservoir selection, date-range filtering, CSV/PDF export (role-gated). |
| **FR-UI-6** | Early-warning alerts view as the **central feature**: list, severity, acknowledgement, history; admin pipeline/system-health view. |
| **FR-UI-7** | Modern, clean, professional, responsive, WCAG-aware UI; loading / empty / error / stale states. |
| **AC-6** | All of the above render to the professional UI/UX bar (acceptance centrepiece — see §13). |
| **AC-11 (UI)** | On a risk-threshold crossing, the alert surfaces in-app, is acknowledgeable, and shows timestamped history. |
| **NFR-TIME-2** | Last-acquisition date + data-freshness/staleness indicators shown everywhere data is shown. |
| **NFR-SEC-1** | Role-based routing + action gating for all 5 roles. |

Out of scope (other tracks): the API itself, auth token issuance/validation logic (we consume it), ML/pipeline internals, external alert push (v2, §2 Non-Goals).

---

## 2. Upstream dependencies — the API endpoint catalogue we consume

We depend entirely on FastAPI (§5.5, FR-API-1..5). Endpoints we **need** (this is the contract we ask the backend to confirm — see §11 for exact shapes and gaps):

| # | Method · path | Purpose | Roles |
| --- | --- | --- | --- |
| E1 | `GET /api/v1/auth/login` (or `POST /token`) + `GET /api/v1/auth/me` | Login, current user + role + permissions. | all |
| E2 | `GET /api/v1/reservoirs` | Reservoir catalogue + metadata (id, name, basin, FRL, capacity, centroid). | all |
| E3 | `GET /api/v1/reservoirs/{id}` | Single reservoir detail + config. | all |
| E4 | `GET /api/v1/reservoirs/{id}/status` | Latest status: fill %, volume BCM, level, surface area, last-acquisition date, freshness. | all |
| E5 | `GET /api/v1/reservoirs/{id}/timeseries?from=&to=&series=` | Historical series (current-yr/last-yr/normal) for trend charts. | all |
| E6 | `GET /api/v1/reservoirs/{id}/forecast` | 1–14 day forecast w/ prediction intervals + model version. | all |
| E7 | `GET /api/v1/reservoirs/{id}/release-risk` | Risk level, probability, lead time, contributing factors. | all |
| E8 | `GET /api/v1/reservoirs/{id}/accuracy` | Estimate-vs-ground-truth pairs + backtest metrics (MAE/RMSE, forecast skill). | Analyst, Admin, DMA |
| E9 | `GET /api/v1/geo/aoi?reservoir_id=` | AOI polygon GeoJSON. | all |
| E10 | `GET /api/v1/geo/water-extent?reservoir_id=&date=` | Current water-extent (mask) GeoJSON. | all |
| E11 | `GET /api/v1/geo/catchment?reservoir_id=` | Catchment polygon GeoJSON. | all |
| E12 | `GET /api/v1/geo/reservoir-markers` | FeatureCollection of all reservoirs w/ risk level for map markers. | all |
| E13 | `GET /api/v1/alerts?status=&severity=&reservoir_id=&from=&to=` | Alert list + history. | all (public sees public-class only) |
| E14 | `POST /api/v1/alerts/{id}/acknowledge` | Acknowledge an alert. | DMA, Operator, Admin |
| E15 | `GET /api/v1/export/report?reservoir_id=&from=&to=&format=csv\|pdf` | Server-rendered situation report / CSV. | DMA, Operator, Analyst, Admin |
| E16 | `GET /api/v1/admin/health` | Pipeline + system health (run status, durations, freshness lag). | Admin |
| E17 | `GET/POST/PATCH /api/v1/admin/reservoirs` | Reservoir + AOI management. | Admin |
| E18 | `POST /api/v1/admin/pipelines/{name}/trigger` + `GET .../runs` | Trigger/monitor pipeline runs. | Admin |
| E19 | `GET/POST/PATCH /api/v1/admin/users` | User + role management. | Admin |

All served data must satisfy **NFR-TIME-3** (< 1 s p95) so client-side caching is for UX smoothness, not to mask slow APIs.

---

## 3. Downstream consumers — roles & what each sees

| Role (§3) | Landing route | Sees | Can do |
| --- | --- | --- | --- |
| **Disaster-Management Authority** (primary) | `/alerts` | Map, KPIs, forecast, **release-risk outlook**, alerts, accuracy (read), export | Acknowledge alerts, export reports |
| **Dam Operator** | `/` (overview) | Map, KPIs, forecast, release-risk outlook, alerts, export | Acknowledge alerts, export |
| **Analyst** | `/reservoirs/:id/accuracy` | Everything analytical + **accuracy/estimate-vs-truth**, water masks, export | Export; no admin |
| **Admin** | `/admin/health` | Everything + **admin** (health, reservoir/AOI/user mgmt, pipeline triggers) | All management actions |
| **Public viewer** | `/public` | Public map + public release-risk status only | No export, no ack, no admin |

Role → capability gating is centralised in a `permissions` map keyed off `auth/me` (E1), enforced at **route guard** and **component** level (never trust the UI alone — API re-enforces, FR-API-3).

---

## 4. Page / route map + component tree (centrepiece)

Routing via **React Router v6** (data-router). Layout: persistent `AppShell` (top bar: reservoir picker, date-range, freshness pill, user menu; left nav role-filtered). Every data view wraps in `<AsyncBoundary>` (Suspense + ErrorBoundary) giving uniform **loading / empty / error / stale** states (FR-UI-7).

```
<RootProviders> (QueryClient, AuthProvider, ThemeProvider, Router)
└─ <AppShell>  [TopBar: <ReservoirPicker> <DateRangePicker> <FreshnessPill> <UserMenu>]
   │           [SideNav: role-filtered links]
   ├─ /login                         → <LoginPage>                         [public]
   ├─ /                              → <OverviewPage>                      [authed]
   ├─ /map                           → <MapPage>                           [authed]
   ├─ /reservoirs/:id                → <ReservoirDetailPage>               [authed]
   ├─ /reservoirs/:id/forecast       → <ForecastPage>                      [authed]
   ├─ /reservoirs/:id/accuracy       → <AccuracyPage>                      [Analyst/Admin/DMA]
   ├─ /alerts                        → <AlertsPage>                        [authed; public→subset]
   ├─ /alerts/:id                    → <AlertDetailPage>                   [authed]
   ├─ /admin/health                  → <AdminHealthPage>                   [Admin]
   ├─ /admin/reservoirs              → <AdminReservoirsPage>               [Admin]
   ├─ /admin/users                   → <AdminUsersPage>                    [Admin]
   ├─ /public                        → <PublicDashboardPage>               [public, no auth]
   └─ *                              → <NotFound> / <Forbidden>
```

### 4.1 `<MapPage>` — FR-UI-1, FR-UI-3
- **Components:** `MapContainer` (react-leaflet) › `TileLayer` (OpenStreetMap / open basemap), `ReservoirMarkerLayer` (risk-coloured `CircleMarker`s + `Tooltip`/`Popup`), `AOILayer` (GeoJSON), `WaterExtentLayer` (GeoJSON, toggleable), `CatchmentLayer` (GeoJSON, toggleable), `MapLegend` (risk colour key), `LayerToggleControl`, `RiskMarkerPopup` (mini KPI + risk + "view detail").
- **Hooks:** `useReservoirMarkers()` → E12; `useAOI(id)` → E9; `useWaterExtent(id, date)` → E10; `useCatchment(id)` → E11.
- **Roles:** all. Public viewer gets markers + public AOI only (no water-mask toggle if backend gates it).

### 4.2 `<OverviewPage>` — FR-UI-2
- **Components:** `KpiCardGrid` › 4× `KpiCard` (FillPct, VolumeBCM, LevelVsFRL, SurfaceArea, each with delta + `FreshnessBadge`); `MiniMap` (embedded `<MapPage>` markers); `RiskSummaryStrip` (per-reservoir risk chips); `RecentAlertsWidget` (top 5 from E13).
- **Hooks:** `useReservoirStatus(id)` → E4; `useReleaseRisk(id)` → E7; `useReservoirMarkers()` → E12; `useAlerts({limit:5})` → E13.

### 4.3 `<ReservoirDetailPage>` — FR-UI-2, FR-UI-3
- **Components:** `ReservoirHeader` (name, basin, FRL, freshness); `KpiCardGrid`; `TrendChart` (current-yr vs last-yr vs normal, fill%/level/volume selectable); `ReleaseRiskOutlookPanel` (risk badge, probability gauge, lead-time, `ContributingFactorsList`); `ForecastChartPreview` (link to full); `ExportMenu` (role-gated).
- **Hooks:** `useReservoirStatus` → E4; `useTimeseries(id,range,series)` → E5; `useReleaseRisk` → E7; `useForecast(id)` → E6.

### 4.4 `<ForecastPage>` — FR-UI-3
- **Components:** `ForecastChart` (line + shaded prediction-interval band, 1–14 day x-axis, FRL reference line, baseline overlay); `HorizonTable` (per-day predicted value + interval); `ReleaseRiskOutlookPanel`; `ModelVersionBadge`; `StaleDataBanner` (NFR-REL-6 — forecast-from-last-known when imagery stale).
- **Hooks:** `useForecast` → E6; `useReleaseRisk` → E7.

### 4.5 `<AccuracyPage>` — FR-UI-4 (Analyst-centric)
- **Components:** `EstimateVsGroundTruthChart` (scatter + 1:1 line); `ResidualChart` (residual vs date); `AccuracyMetricsTable` (MAE/RMSE/MAPE on fill%/volume/level; forecast skill vs baseline; backtest-derived, per §7.1/AC-5 — labelled "historical backtest", not live); `BacktestCaseStudyList`.
- **Hooks:** `useAccuracy(id)` → E8.
- **Roles:** Analyst, Admin, DMA. Hidden from Operator/Public via route guard.

### 4.6 `<AlertsPage>` / `<AlertDetailPage>` — FR-UI-6, AC-11 (central feature)
- **Components:** `AlertFilters` (severity, type, reservoir, status, date range); `AlertList` › `AlertRow` (severity badge, type icon, reservoir, triggered_at, ack state); `AlertDetailPanel` (message, contributing factors, linked release-risk, audit trail timestamps); `AcknowledgeButton` (role-gated → E14, optimistic update + invalidation); `AlertHistoryTab` (resolved/acknowledged history).
- **Hooks:** `useAlerts(filters)` → E13; `useAcknowledgeAlert()` (mutation) → E14.
- **Severity colours** mirror risk levels (Low/Watch/Warning/Imminent) plus secondary types (approaching-FRL, rapid-rise, data-quality).

### 4.7 Admin pages — FR-UI-6, FR-API-5
- `<AdminHealthPage>`: `PipelineStatusBoard` (RS/DE/ML run cards: status, duration, row counts, last success, freshness lag), `RunHistoryTable`, `TriggerPipelineButton` (E18), `SystemHealthCards` (API/DB). Hooks: `usePipelineHealth()` → E16; `useTriggerPipeline()` → E18.
- `<AdminReservoirsPage>`: `ReservoirTable`, `ReservoirEditDrawer` (metadata + AOI GeoJSON upload/preview on a mini-map), CRUD via E17.
- `<AdminUsersPage>`: `UserTable`, `UserRoleEditor`, CRUD via E19.

### 4.8 `<PublicDashboardPage>` — public viewer
- Stripped `MapPage` + `RiskSummaryStrip` + public alerts only. No `ExportMenu`, no `AcknowledgeButton`, no admin nav. Served at `/public` (no auth required, read-only public endpoints).

### 4.9 Shared / cross-cutting components
`AsyncBoundary`, `LoadingSkeleton`, `EmptyState`, `ErrorState` (with retry), `FreshnessBadge`/`FreshnessPill` (green ≤ revisit window, amber stale, red very stale per NFR-TIME-2), `RiskBadge`, `SeverityBadge`, `RoleGate` (renders children only if permission), `ExportMenu`, `ProtectedRoute`, `ReservoirPicker`, `DateRangePicker`, `ProbabilityGauge`, `ContributingFactorsList`.

---

## 5. State & data-fetching approach

- **Server state:** **TanStack Query (React Query) v5** — caching, background refetch, stale-while-revalidate, retry/backoff, query invalidation on mutations (alert ack, admin writes). One query key namespace per endpoint, e.g. `['status', id]`, `['forecast', id]`, `['alerts', filters]`.
- **Polling / freshness:** background `refetchInterval` for live-ish views (alerts ~60 s; status/risk ~5 min — bounded by satellite revisit, NFR-TIME-2, so aggressive polling is pointless). `FreshnessBadge` reads `last_acquisition_date` from payload, not poll time.
- **Global UI state:** lightweight **Zustand** store for cross-cutting selections (selected reservoir, date range, layer toggles, theme). Auth/session in `AuthProvider` context (token in memory + httpOnly cookie preferred; refresh on 401).
- **URL state:** reservoir id and date range are reflected in the URL (search params) so views are shareable/bookmarkable and deep-linkable from alerts.
- **Forms:** **React Hook Form + Zod** for admin forms and login; Zod schemas double as runtime API-response validators (typed boundary).
- **Error handling:** centralised Axios/fetch client with interceptors → 401 redirects to login, 403 → `<Forbidden>`, 5xx → toast + `ErrorState`. No silent failures (surface every error per FR-UI-7).

---

## 6. Design-system & accessibility approach

- **Component system:** **shadcn/ui** (Radix primitives + Tailwind). Rationale: Radix gives accessible-by-default primitives (focus management, ARIA, keyboard nav) which directly serve WCAG (NFR-UX-1); shadcn is copy-in (no heavy runtime, full control over the "modern/clean/professional" look), pairs cleanly with Tailwind tokens, and is lighter than MUI for a bespoke disaster-ops aesthetic. (MUI is the fallback if the team prefers a batteries-included kit.)
- **Theming / tokens:** Tailwind design tokens for colour, spacing, type scale; semantic risk-colour tokens (`--risk-low/watch/warning/imminent`) defined once and reused on map markers, badges, alerts so the visual language is consistent (and colour-blind-safe — pair colour with icon/label, never colour alone).
- **Accessibility (WCAG-aware):** semantic landmarks, keyboard-navigable map controls and tables, visible focus rings, ARIA live-region announcing new high-severity alerts, ≥ 4.5:1 contrast, `prefers-reduced-motion` respected for chart/animation, all icons labelled. Charts ship an accessible data-table fallback. Target **WCAG 2.1 AA**.
- **Responsive:** mobile-first; map and KPI grid reflow to single column; tables → card lists on small screens; serves mobile browsers (no native app, §2).
- **States:** every async view has explicit skeleton / empty / error / stale variants (FR-UI-7) via `AsyncBoundary`.

---

## 7. Library choices (with rationale)

| Concern | Choice | Rationale |
| --- | --- | --- |
| Build / framework | **React + Vite + TypeScript** | Mandated stack; Vite = fast HMR, simple build. |
| Map | **react-leaflet + Leaflet** | Mandated; mature GeoJSON support for AOI/water-extent/catchment overlays. |
| Charts | **Recharts** | Declarative React API, fast to build trend/forecast/scatter, easy shaded prediction-interval bands (`Area`), good-enough a11y with table fallback. (visx is the fallback if we need fully custom conformal-band rendering or large-series perf.) |
| Component system | **shadcn/ui (Radix + Tailwind)** | Accessible primitives, bespoke professional look, light footprint. |
| Server state | **TanStack Query v5** | Caching, background refresh, invalidation — ideal for read-heavy dashboard. |
| Client state | **Zustand** | Minimal global store for selections/toggles. |
| Routing | **React Router v6 (data router)** | Loaders, nested layouts, route guards. |
| Forms + validation | **React Hook Form + Zod** | Typed forms + runtime response validation at the API boundary. |
| HTTP | **Axios** (or fetch wrapper) | Interceptors for auth/error handling. |
| PDF (client fallback) | server-rendered preferred (E15); **react-pdf**/print-CSS fallback | Keep heavy report layout server-side; client handles CSV download + print view. |
| Testing | **Vitest + React Testing Library + Playwright + MSW** | Unit/component + e2e + API mocking. |

---

## 8. Interfaces / contracts we depend on (flag gaps for backend)

We need these **response shapes** confirmed. Where the existing frozen contract (`docs/contracts/observation-and-abt.md`) already defines fields, we reuse them; the serving-layer shapes below are **new and must be agreed with the API track**.

```ts
// E4 status
interface ReservoirStatus {
  reservoir_id: string; name: string; basin: string;
  fill_pct: number; volume_bcm: number; level_m: number; frl_m: number;
  surface_area_km2: number; area_confidence: number;
  last_acquisition_date: string; // ISO; drives FreshnessBadge
  is_extrapolated: boolean; row_quality: 'ok'|'low_confidence'|'quarantine';
}
// E6 forecast — 1..14 day, conformal intervals (ADR-0006)
interface Forecast {
  reservoir_id: string; issued_at: string; model_version: string;
  horizons: { horizon_day: number; date: string;
              pct_filled: number; lower: number; upper: number;
              level_m: number; volume_bcm: number; }[];
  baseline?: { horizon_day: number; pct_filled: number; }[]; // persistence/climatology
}
// E7 release-risk
interface ReleaseRisk {
  reservoir_id: string; run_timestamp: string; model_version: string;
  risk_level: 'Low'|'Watch'|'Warning'|'Imminent';
  release_probability: number; estimated_lead_time_days: number | null;
  contributing_factors: { name: string; value: number|string; weight?: number }[];
}
// E8 accuracy (backtest-derived, NOT live — ADR-0005)
interface Accuracy {
  reservoir_id: string; basis: 'historical_backtest';
  metrics: { name: string; value: number; unit: string }[]; // MAE/RMSE/MAPE, skill vs baseline
  pairs: { date: string; estimated_pct: number; ground_truth_pct: number; residual: number; }[];
}
// E13 alert
interface Alert {
  id: string; reservoir_id: string;
  type: 'flood-release'|'approaching-FRL'|'rapid-rise'|'data-quality';
  severity: 'Low'|'Watch'|'Warning'|'Imminent';
  triggered_at: string; message: string; contributing_factors: string[];
  release_risk_ref?: string;
  acknowledged_by?: string; acknowledged_at?: string; resolved_at?: string;
}
// E12 markers — GeoJSON FeatureCollection, each feature.properties carries:
//   { reservoir_id, name, risk_level, fill_pct, last_acquisition_date }
// E9/E10/E11 — standard GeoJSON (Polygon/MultiPolygon) ready for Leaflet.
```

**Gaps to flag to backend (BLOCKERS / align early):**
1. **Auth mechanism** — confirm OAuth2 password/JWT vs cookie session, refresh-token flow, and the exact `auth/me` `permissions`/`role` shape (drives all RBAC gating). *(Blocker for T-02.)*
2. **`/geo/reservoir-markers` (E12)** — confirm a single all-reservoirs FeatureCollection with `risk_level` baked into `properties` (avoids N calls). *(Blocker for map.)*
3. **Water-extent (E10)** — confirm GeoJSON vs raster tiles; if masks are large, request simplified GeoJSON or a tile endpoint + a `date` to pick the acquisition.
4. **Export (E15)** — confirm server renders PDF/CSV (preferred) so the client just triggers download; agree which fields/sections.
5. **Trend series (E5)** — confirm `series` enum returns `current_year` / `last_year` / `normal` aligned on day-of-year for overlay.
6. **Public scoping** — confirm which endpoints/fields are exposed unauthenticated for the public viewer.
7. **Freshness fields** — confirm `last_acquisition_date` + per-source `freshness_flags` are present on status/forecast (NFR-TIME-2, NFR-REL-6).
8. **Pagination / filtering** — confirm query params + envelope for `/alerts` and admin lists.
9. **CORS + error envelope** — confirm a consistent error JSON shape `{ code, message, detail }`.

---

## 9. Task breakdown (sequenced, with acceptance checks)

| ID | Task | Acceptance check |
| --- | --- | --- |
| **T-01** | Scaffold `web/` (Vite+TS), Tailwind+shadcn, ESLint/Prettier, Vitest, Playwright, MSW; CI lint+test. | `npm run dev/build/test/lint` all green in CI. |
| **T-02** | Auth + RBAC: `AuthProvider`, login page, token/refresh, `ProtectedRoute`, `RoleGate`, permission map from E1. | Each role lands on correct route; forbidden routes → `<Forbidden>`; 401 → login. |
| **T-03** | `AppShell` + routing skeleton + `AsyncBoundary` + loading/empty/error/stale primitives + `FreshnessBadge`. | All routes resolve; uniform states render; freshness pill computes from date. |
| **T-04** | Typed API client (Axios + Zod validators) + React Query setup + query-key map; MSW fixtures for every endpoint. | All E1–E19 typed + mocked; interceptors handle 401/403/5xx. |
| **T-05** | **Map** (FR-UI-1/3): markers risk-coloured, AOI/water-extent/catchment overlays, legend, toggles, popups. | Three pilot reservoirs render with correct risk colours + overlays from mocks. |
| **T-06** | **Overview + KPI cards + trend charts** (FR-UI-2): KpiCardGrid, TrendChart (cur/last/normal). | KPIs match status payload; trend overlays 3 series; responsive reflow. |
| **T-07** | **Forecast + release-risk outlook** (FR-UI-3): ForecastChart w/ interval band + FRL line + baseline; RiskOutlookPanel (level, prob gauge, lead time, factors). | 1–14 day band renders; risk panel shows all four fields; stale banner on stale data. |
| **T-08** | **Alerts** (FR-UI-6, AC-11): list, filters, detail, acknowledge (gated), history, audit timestamps, a11y live-region. | Ack updates optimistically + invalidates; history shows acked/resolved; public sees subset. |
| **T-09** | **Accuracy view** (FR-UI-4): estimate-vs-truth scatter, residuals, metrics table (labelled backtest), case studies. | Analyst/Admin/DMA only; metrics + pairs render; hidden from Operator/Public. |
| **T-10** | **Export** (FR-UI-5): CSV/PDF via E15, role-gated ExportMenu + date-range scoping. | Authorised roles download; unauthorised don't see control. |
| **T-11** | **Admin** (FR-API-5): health board + run history + trigger; reservoir/AOI mgmt; user mgmt. | Admin-only; trigger fires; AOI upload previews on mini-map; CRUD works. |
| **T-12** | **Public dashboard** + responsive/a11y audit + WCAG 2.1 AA pass (axe) + polish. | axe: 0 criticals; keyboard-only nav works; Lighthouse a11y ≥ 95. |
| **T-13** | **e2e suite** (Playwright) covering the 5 role journeys + AC-6/AC-11 flows. | All role journeys green in CI against mocked/staging API. |

Sequencing: T-01→T-04 are foundation (serial). T-05..T-11 are largely parallel once T-04 lands. T-12/T-13 gate release.

---

## 10. Testing strategy

- **Unit (Vitest):** pure helpers — freshness classification, risk→colour mapping, permission checks, Zod validators, chart data transforms.
- **Component (RTL + MSW):** each page/view against mocked endpoints; assert loading/empty/error/stale states, role gating (`RoleGate`), and a11y roles. Map layers tested via react-leaflet test harness (assert layers/markers mounted with correct props).
- **e2e (Playwright):** the five role journeys end-to-end — Public sees map only; DMA acknowledges an alert and exports; Analyst opens accuracy; Admin triggers a pipeline; Operator views forecast. Covers **AC-6** (all dashboard elements render) and **AC-11** (alert crossing → ack → history).
- **Accessibility:** `@axe-core/playwright` on every page in CI; manual keyboard + screen-reader spot-checks.
- **Visual/regression (optional):** Playwright screenshots for the map + charts.
- **Contract safety:** Zod runtime validation fails loudly in dev if a payload drifts from §8 shapes — early-warning on backend contract changes.

---

## 11. Risks & open decisions

| Risk / decision | Notes / mitigation | Affects |
| --- | --- | --- |
| **Auth shape undefined** | Blocks RBAC; confirm JWT-vs-cookie + `me` permissions early (gap #1). | Backend, T-02 |
| **Water-mask payload size** | Large GeoJSON can stall the map; request simplified GeoJSON or tiles (gap #3). | Backend |
| **PDF rendering location** | Prefer server-rendered reports; client-side PDF is heavy/fragile. Decide now (gap #4). | Backend |
| **Risk colour semantics** | Lock the 4-tier palette + colour-blind-safe pairing once, share with map/badges/alerts. | Design |
| **Public scoping** | Which data is public vs authed must be backend-enforced, not just hidden in UI (gap #6). | Backend, Security |
| **Polling cadence** | Bounded by ~6–12 day revisit (NFR-TIME-2) — avoid over-polling; rely on freshness flags + NFR-REL-6 stale messaging. | — |
| **shadcn vs MUI** | Recommending shadcn; if team wants batteries-included, switch — decide before T-01. | Frontend |
| **Recharts vs visx** | Recharts default; revisit for conformal-band perf on long horizons. | Frontend |
| **Backtest-only accuracy framing** | Accuracy view must clearly label metrics "historical backtest, not live" (ADR-0001/0005) to avoid over-claiming. | Product/Design |

---

## 12. Mapping to acceptance criteria (AC-6 especially)

| AC | Where satisfied |
| --- | --- |
| **AC-6** (map, risk indicators, alerts, KPI cards, trend/forecast charts, accuracy, pro UI bar) | T-05 (map+risk), T-06 (KPI+trend), T-07 (forecast+risk), T-08 (alerts), T-09 (accuracy), T-12 (UI/a11y bar). The dashboard as a whole = AC-6. |
| **AC-11** (in-app alert on threshold crossing, timestamped acknowledgeable history) | T-08 (alerts list/detail/ack/history + audit timestamps). |
| **NFR-UX-1 / FR-UI-7** | T-03 + T-12 (design system, responsive, a11y, loading/empty/error/stale). |
| **NFR-TIME-2** (freshness) | T-03 `FreshnessBadge` + T-07 stale banner (NFR-REL-6). |
| **NFR-SEC-1** (RBAC, UI side) | T-02 route guards + `RoleGate`, re-enforced by API. |
```
