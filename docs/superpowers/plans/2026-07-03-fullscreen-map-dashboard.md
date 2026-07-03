# Fullscreen Map Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current two-pane dashboard with a fullscreen, GSAP-animated, map-first console: left sidebar (3 reservoir buttons + Dashboard), docked sparkline timeline scrubbing real Sentinel-1 imagery via live Earth Engine tiles, vertical area meter, and an all-reservoir analytics dashboard view.

**Architecture:** One shell (`Sidebar` + `Stage`); Zustand holds UI state (`view`, `selected`, `activeDate`, `playing`); TanStack Query caches all server state; every GSAP timeline lives in `web/src/lib/motion.ts`. Three additive read-only API endpoints (acquisitions, sar-tiles, rainfall) plus a loader that upserts the Stage-1.2 backfill CSVs into `observation`.

**Tech Stack:** React 18 + TypeScript (strict) + Vite · Leaflet/react-leaflet · Recharts · GSAP + @gsap/react · Zustand · @tanstack/react-query · Vitest (store tests) · FastAPI + SQLAlchemy Core (backend) · earthengine-api (tile minting only).

**Spec:** `docs/superpowers/specs/2026-07-03-fullscreen-map-dashboard-design.md` — read it before starting.

## Global Constraints

- No Tailwind, no shadcn. Styling = `web/src/styles/tokens.css` + component CSS in `web/src/styles.css`.
- New frontend deps allowed: `gsap`, `@gsap/react`, `zustand`, `@tanstack/react-query`, dev: `vitest`. Nothing else.
- API changes are additive read-only; **no** Alembic migration, **no** `contract_version` bump.
- The API must run fully without GEE credentials — only `/sar-tiles` degrades (503).
- Every backend task passes: `uv run ruff check api scripts tests && uv run mypy api scripts && uv run pytest tests/unit tests/contract -q` (integration tests skip without a DB — keep them logically correct for CI).
- Every frontend task passes: `cd web && npm run build` (tsc `--noEmit` strict + vite build).
- Honesty states are requirements, not polish: abstained scenes = visible gaps; GEE down = "live imagery unavailable" chip; empty rainfall = "awaiting live forcing".
- Windows host: run all commands from repo root `D:\projects\reservoir_analytics` unless a `cd web` is shown.
- Commit after every task (message given per task). Never `--no-verify`.

## File Structure (final state)

```
scripts/load_backfill.py                 # backfill CSV -> observation upsert
api/src/api/gee_tiles.py                 # EE tile-URL minting + TTL cache (optional GEE dep)
api/src/api/repositories.py              # + acquisitions(), rainfall()
api/src/api/routes.py                    # + 3 endpoints
api/src/api/schemas.py                   # + AcquisitionOut, SarTileOut, RainfallPointOut
tests/integration/test_load_backfill.py  # loader integration test
tests/integration/test_api.py            # + endpoint tests
tests/unit/test_gee_tiles.py             # tile cache + 503 unit tests
web/src/styles/tokens.css                # design tokens
web/src/lib/store.ts                     # Zustand store
web/src/lib/store.test.ts                # Vitest store tests
web/src/lib/api.ts                       # typed client (rewrite)
web/src/lib/queries.ts                   # TanStack Query hooks
web/src/lib/motion.ts                    # ALL GSAP timelines
web/src/components/Sidebar.tsx
web/src/components/ReservoirButton.tsx
web/src/components/stage/MapView.tsx
web/src/components/stage/SarTileLayer.tsx
web/src/components/stage/TimelineDock.tsx
web/src/components/stage/AreaMeter.tsx
web/src/components/stage/DashboardView.tsx
web/src/App.tsx                          # shell only (rewrite)
web/src/types.ts                         # + Acquisition, SarTile, RainfallPoint
DELETED: web/src/api.ts, web/src/components/ReservoirMap.tsx,
         web/src/components/TrendChart.tsx, web/src/components/ForecastChart.tsx
```

---

### Task 1: Backfill loader — `observation` gets the real series

**Files:**
- Create: `scripts/load_backfill.py`
- Test: `tests/integration/test_load_backfill.py`

**Interfaces:**
- Consumes: `data/backfill/area_series_<slug>.csv` (columns: `scene_id, acquisition_date, orbit_relative, pass_direction, status, area_km2, threshold_db, otsu_eta, valley_ratio, separability, detail`).
- Produces: rows in `observation` with `extraction_method='otsu_vh'`, real `scene_ids`; function `load_backfill(session, csv_dir: Path) -> dict[str, int]` returning `{"loaded": n, "skipped_non_ok": m}`.

- [ ] **Step 1: Check the existing observation upsert columns** (mirror them exactly — do not invent columns)

Run: `grep -n "INSERT INTO observation" -A 20 pipelines/remote_sensing/src/remote_sensing/pipeline.py`
Expected: an upsert listing columns `reservoir_id, acquisition_date, surface_area, area_confidence, extraction_method, layover_shadow_fraction, scene_ids` (plus `ON CONFLICT`). If the real column list differs from the code below, match the file, not this plan.

- [ ] **Step 2: Write the failing integration test**

```python
# tests/integration/test_load_backfill.py
"""Loader: backfill CSVs -> real observation rows (spec: data prerequisite)."""

from pathlib import Path

from sqlalchemy import text

from scripts.load_backfill import load_backfill

CSV = """scene_id,acquisition_date,orbit_relative,pass_direction,status,area_km2,threshold_db,otsu_eta,valley_ratio,separability,detail
S1A_TEST_0001,2020-01-05,27,ASC,ok,120.5,-21.4,0.86,0.21,0.92,
S1A_TEST_0002,2020-01-17,27,ASC,abstain,,-20.1,0.55,0.81,0.10,histogram not bimodal
S1A_TEST_0003,2020-01-29,27,ASC,ok,118.2,-21.9,0.84,0.25,0.91,
"""


def test_load_backfill_upserts_ok_rows_only(db_session, seeded_reservoirs, tmp_path):
    csv_dir = tmp_path / "backfill"
    csv_dir.mkdir()
    (csv_dir / "area_series_gobind_sagar.csv").write_text(CSV, encoding="utf-8")

    result = load_backfill(db_session, csv_dir)
    assert result == {"loaded": 2, "skipped_non_ok": 1}

    rows = db_session.execute(
        text(
            "SELECT acquisition_date, surface_area, extraction_method, scene_ids "
            "FROM observation WHERE reservoir_id = 'gobind_sagar' ORDER BY acquisition_date"
        )
    ).fetchall()
    assert len(rows) == 2
    assert float(rows[0].surface_area) == 120.5
    assert rows[0].extraction_method == "otsu_vh"
    assert rows[0].scene_ids == ["S1A_TEST_0001"]

    # idempotent: re-load converges, no duplicates
    result2 = load_backfill(db_session, csv_dir)
    assert result2["loaded"] == 2
    n = db_session.execute(
        text("SELECT count(*) FROM observation WHERE reservoir_id='gobind_sagar'")
    ).scalar()
    assert n == 2
```

Note: `db_session` and reservoir seeding fixtures — check `tests/integration/conftest.py` for the exact fixture names already used by `tests/integration/test_de_pipeline.py` and reuse those (there is an existing pattern that seeds the three reservoirs; if the seeding fixture is named differently, adapt the test signature, not the conftest).

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_load_backfill.py -q`
Expected: SKIP without a local DB (that is the repo's integration pattern), or FAIL with `ModuleNotFoundError: scripts.load_backfill` when a DB is available. Either confirms the test is wired.

- [ ] **Step 4: Implement the loader**

```python
# scripts/load_backfill.py
"""Load Stage-1.2 backfill CSVs into ``observation`` (Replan.md data prerequisite).

Only ``status == 'ok'`` rows carry an area; abstain/error scenes are counted but never
loaded (a gap is honest, a fake area is not). Upsert converges on re-run and replaces
any stub row for the same (reservoir, date).
Run: uv run python scripts/load_backfill.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.db.session import session_scope

ROOT = Path(__file__).resolve().parents[1]
BACKFILL_DIR = ROOT / "data" / "backfill"

_UPSERT = text(
    """
    INSERT INTO observation
        (reservoir_id, acquisition_date, surface_area, area_confidence,
         extraction_method, layover_shadow_fraction, scene_ids)
    VALUES
        (:rid, :date, :area, :conf, 'otsu_vh', 0.0, ARRAY[:scene_id])
    ON CONFLICT (reservoir_id, acquisition_date) DO UPDATE SET
        surface_area = EXCLUDED.surface_area,
        area_confidence = EXCLUDED.area_confidence,
        extraction_method = EXCLUDED.extraction_method,
        layover_shadow_fraction = EXCLUDED.layover_shadow_fraction,
        scene_ids = EXCLUDED.scene_ids
    """
)


def load_backfill(session: Session, csv_dir: Path) -> dict[str, int]:
    loaded = skipped = 0
    for csv_path in sorted(csv_dir.glob("area_series_*.csv")):
        rid = csv_path.stem.replace("area_series_", "")
        with csv_path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row["status"] != "ok" or not row["area_km2"]:
                    skipped += 1
                    continue
                session.execute(
                    _UPSERT,
                    {
                        "rid": rid,
                        "date": row["acquisition_date"],
                        "area": float(row["area_km2"]),
                        # v1 confidence = separability (compactness/layover unavailable
                        # in batch mode; documented in Replan.md)
                        "conf": float(row["separability"]),
                        "scene_id": row["scene_id"],
                    },
                )
                loaded += 1
    return {"loaded": loaded, "skipped_non_ok": skipped}


def main() -> int:
    with session_scope() as session:
        result = load_backfill(session, BACKFILL_DIR)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Check `core/src/core/db/session.py` for the exact `session_scope` signature (it exists — used across the pipelines); if it requires a `readonly` argument, pass `readonly=False`.

- [ ] **Step 5: Verify gates**

Run: `uv run ruff check scripts tests && uv run mypy scripts && uv run pytest tests/integration/test_load_backfill.py -q`
Expected: lint/type clean; test SKIP (no DB) or PASS (DB up).

- [ ] **Step 6: Commit**

```bash
git add scripts/load_backfill.py tests/integration/test_load_backfill.py
git commit -m "feat(data): loader upserts Stage-1.2 backfill into observation"
```

---

### Task 2: `GET /reservoirs/{id}/acquisitions` endpoint

**Files:**
- Modify: `api/src/api/repositories.py` (add function at end)
- Modify: `api/src/api/routes.py`, `api/src/api/schemas.py`
- Test: `tests/integration/test_api.py` (append)

**Interfaces:**
- Consumes: `observation` rows from Task 1.
- Produces: `GET /reservoirs/{id}/acquisitions` → `list[AcquisitionOut]`; repository function `acquisitions(db, rid) -> list[dict]` with keys `date, area_km2, confidence`.

- [ ] **Step 1: Write the failing test** (append to `tests/integration/test_api.py`, reusing its existing client/seed fixtures — read the top of the file first and follow its established pattern for seeding observations)

```python
def test_acquisitions_endpoint_serves_real_series(client, seeded_observation_rows):
    r = client.get("/reservoirs/gobind_sagar/acquisitions")
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 1
    first = body[0]
    assert set(first) == {"date", "area_km2", "confidence"}
    dates = [row["date"] for row in body]
    assert dates == sorted(dates)


def test_acquisitions_unknown_reservoir_404(client):
    assert client.get("/reservoirs/nope/acquisitions").status_code == 404
```

If `test_api.py` has no fixture seeding non-stub observations, add one in that file (not conftest) that inserts two `otsu_vh` rows via `db_session.execute(text(...))` mirroring Task 1's upsert.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_api.py -k acquisitions -q`
Expected: SKIP (no DB) or FAIL 404/AttributeError.

- [ ] **Step 3: Implement**

`api/src/api/schemas.py` — add:

```python
class AcquisitionOut(BaseModel):
    date: str
    area_km2: float
    confidence: float
```

`api/src/api/repositories.py` — add (follow the module's existing `text()` + bind-param style; reuse its existing "reservoir exists" helper if present, otherwise the same 404 pattern the other functions use):

```python
def acquisitions(db: Session, rid: str) -> list[dict]:
    """Non-stub SAR acquisition series for the timeline (spec endpoint 1)."""
    rows = db.execute(
        text(
            "SELECT acquisition_date::text AS date, surface_area, area_confidence "
            "FROM observation "
            "WHERE reservoir_id = :rid AND extraction_method <> 'stub' "
            "ORDER BY acquisition_date"
        ),
        {"rid": rid},
    ).fetchall()
    return [
        {"date": r.date, "area_km2": float(r.surface_area), "confidence": float(r.area_confidence)}
        for r in rows
    ]
```

`api/src/api/routes.py` — add (mirror the existing route pattern incl. the 404-on-unknown-reservoir check used by `/reservoirs/{rid}/status`):

```python
@router.get("/reservoirs/{rid}/acquisitions", response_model=list[AcquisitionOut])
def get_acquisitions(rid: str, db: Session = Depends(get_db)) -> list[dict]:
    _ensure_reservoir(db, rid)  # use the module's existing exists/404 helper name
    return repositories.acquisitions(db, rid)
```

- [ ] **Step 4: Verify gates**

Run: `uv run ruff check api tests && uv run mypy api && uv run pytest tests/integration/test_api.py -q && uv run pytest tests/unit tests/contract -q`
Expected: clean; integration SKIP/PASS.

- [ ] **Step 5: Commit**

```bash
git add api tests/integration/test_api.py
git commit -m "feat(api): /reservoirs/{id}/acquisitions serves the SAR timeline"
```

---

### Task 3: SAR tile endpoint with TTL cache + graceful 503

**Files:**
- Create: `api/src/api/gee_tiles.py`
- Modify: `api/src/api/routes.py`, `api/src/api/schemas.py`, `api/src/api/repositories.py`
- Test: `tests/unit/test_gee_tiles.py`

**Interfaces:**
- Produces: `GET /reservoirs/{id}/sar-tiles?date=YYYY-MM-DD` → `SarTileOut {tile_url: str, expires_at: str}` or 503; module API `mint_tile(scene_id: str) -> tuple[str, datetime]`, `get_cached_tile(rid: str, date: str, scene_id: str) -> tuple[str, datetime]`, `GeeUnavailable(Exception)`.

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/unit/test_gee_tiles.py
"""Tile-URL cache + GEE-unavailable behaviour (spec endpoint 2). No live GEE."""

from datetime import datetime, timedelta, timezone

import pytest

from api import gee_tiles


@pytest.fixture(autouse=True)
def clear_cache():
    gee_tiles._CACHE.clear()
    yield
    gee_tiles._CACHE.clear()


def test_cache_hit_within_ttl(monkeypatch):
    calls = []

    def fake_mint(scene_id: str):
        calls.append(scene_id)
        return ("https://tiles/x/{z}/{x}/{y}", datetime.now(timezone.utc) + timedelta(hours=3))

    monkeypatch.setattr(gee_tiles, "mint_tile", fake_mint)
    url1, _ = gee_tiles.get_cached_tile("gobind_sagar", "2020-01-05", "S1A_X")
    url2, _ = gee_tiles.get_cached_tile("gobind_sagar", "2020-01-05", "S1A_X")
    assert url1 == url2
    assert calls == ["S1A_X"]  # second call served from cache


def test_expired_entry_reminted(monkeypatch):
    when = [datetime.now(timezone.utc) - timedelta(minutes=1)]  # already expired

    def fake_mint(scene_id: str):
        return ("https://tiles/x/{z}/{x}/{y}", when[0])

    monkeypatch.setattr(gee_tiles, "mint_tile", fake_mint)
    gee_tiles.get_cached_tile("pong", "2020-01-05", "S1A_Y")
    when[0] = datetime.now(timezone.utc) + timedelta(hours=3)
    _, exp = gee_tiles.get_cached_tile("pong", "2020-01-05", "S1A_Y")
    assert exp == when[0]  # re-minted, not served stale


def test_gee_unavailable_raises(monkeypatch):
    def broken_mint(scene_id: str):
        raise gee_tiles.GeeUnavailable("no credentials")

    monkeypatch.setattr(gee_tiles, "mint_tile", broken_mint)
    with pytest.raises(gee_tiles.GeeUnavailable):
        gee_tiles.get_cached_tile("thein", "2020-01-05", "S1A_Z")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_gee_tiles.py -q`
Expected: FAIL `ModuleNotFoundError: api.gee_tiles`.

- [ ] **Step 3: Implement the module**

```python
# api/src/api/gee_tiles.py
"""Live Sentinel-1 tile URLs for the map (spec endpoint 2).

The only optional-GEE corner of the API: everything else runs credential-free.
EE map ids expire (~4 h), so mints are cached per (reservoir, date) with the
expiry EE reports, minus a safety margin. GeeUnavailable -> the route 503s and
the frontend falls back to basemap + AOI outline (honesty state, spec).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

_CACHE: dict[tuple[str, str], tuple[str, datetime]] = {}
_SAFETY = timedelta(minutes=10)
_VIS = {"bands": ["VH"], "min": -25.0, "max": -5.0}  # dark-water SAR styling


class GeeUnavailable(RuntimeError):
    """GEE credentials missing or initialisation failed — degrade, don't crash."""


def mint_tile(scene_id: str) -> tuple[str, datetime]:
    """One EE round-trip: scene asset -> map id -> tile URL template + expiry."""
    try:
        import ee  # noqa: PLC0415 — optional dependency corner

        key_file = os.environ.get("GEE_SA_KEY_FILE", "geeservice.json")
        if not os.path.exists(key_file):
            raise GeeUnavailable(f"no GEE key file at {key_file}")
        import json

        with open(key_file) as fh:
            info = json.load(fh)
        ee.Initialize(
            ee.ServiceAccountCredentials(info["client_email"], key_file),
            project=info["project_id"],
        )
        img = ee.Image(f"COPERNICUS/S1_GRD/{scene_id}")
        mapid = img.getMapId(_VIS)
        url = mapid["tile_fetcher"].url_format
        # EE does not return an expiry; map ids last ~4 h — advertise 3.5 h.
        return url, datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)
    except GeeUnavailable:
        raise
    except Exception as exc:  # ee import/auth/asset errors — all mean "degrade"
        raise GeeUnavailable(str(exc)) from exc


def get_cached_tile(rid: str, date: str, scene_id: str) -> tuple[str, datetime]:
    key = (rid, date)
    hit = _CACHE.get(key)
    now = datetime.now(timezone.utc)
    if hit and hit[1] - _SAFETY > now:
        return hit
    fresh = mint_tile(scene_id)
    _CACHE[key] = fresh
    return fresh
```

`api/src/api/schemas.py` — add:

```python
class SarTileOut(BaseModel):
    tile_url: str
    expires_at: str
```

`api/src/api/repositories.py` — add a scene-id lookup:

```python
def scene_id_for_date(db: Session, rid: str, date: str) -> str | None:
    row = db.execute(
        text(
            "SELECT scene_ids FROM observation "
            "WHERE reservoir_id = :rid AND acquisition_date = :date "
            "AND extraction_method <> 'stub'"
        ),
        {"rid": rid, "date": date},
    ).fetchone()
    return row.scene_ids[0] if row and row.scene_ids else None
```

`api/src/api/routes.py` — add:

```python
@router.get("/reservoirs/{rid}/sar-tiles", response_model=SarTileOut)
def get_sar_tiles(rid: str, date: str, db: Session = Depends(get_db)) -> dict:
    _ensure_reservoir(db, rid)
    scene_id = repositories.scene_id_for_date(db, rid, date)
    if scene_id is None:
        raise HTTPException(status_code=404, detail=f"no acquisition on {date}")
    try:
        url, expires = gee_tiles.get_cached_tile(rid, date, scene_id)
    except gee_tiles.GeeUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"live imagery unavailable: {exc}") from exc
    return {"tile_url": url, "expires_at": expires.isoformat()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_gee_tiles.py -q && uv run ruff check api tests && uv run mypy api`
Expected: 3 passed; lint/type clean.

- [ ] **Step 5: Commit**

```bash
git add api tests/unit/test_gee_tiles.py
git commit -m "feat(api): live EE SAR tile endpoint with TTL cache and 503 degrade"
```

---

### Task 4: Rainfall endpoint

**Files:**
- Modify: `api/src/api/repositories.py`, `api/src/api/routes.py`, `api/src/api/schemas.py`
- Test: `tests/integration/test_api.py` (append)

**Interfaces:**
- Produces: `GET /reservoirs/{id}/rainfall?window=90` → `list[RainfallPointOut] {date, precip_mm | null}`; empty list when no forcing rows (frontend shows "awaiting live forcing").

- [ ] **Step 1: Confirm the precipitation column name** (do not guess)

Run: `grep -n "precip" core/src/core/models/catchment_forcing.py pipelines/data_engineering/src/data_engineering/forcing.py | head -10`
Expected: the model's mapped column (e.g. `precipitation_mm` or `precipitation`). Use the model's exact name in the SQL below; adjust `AS precip_mm` alias only.

- [ ] **Step 2: Write the failing test** (append to `tests/integration/test_api.py`)

```python
def test_rainfall_endpoint_empty_is_honest(client, seeded_observation_rows):
    r = client.get("/reservoirs/gobind_sagar/rainfall?window=30")
    assert r.status_code == 200
    assert r.json() == []  # no forcing rows seeded -> honest empty, not fake zeros
```

- [ ] **Step 3: Implement**

`api/src/api/schemas.py`:

```python
class RainfallPointOut(BaseModel):
    date: str
    precip_mm: float | None
```

`api/src/api/repositories.py` (replace `<PRECIP_COL>` with the verified column name):

```python
def rainfall(db: Session, rid: str, window_days: int) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT date::text AS date, <PRECIP_COL> AS precip_mm FROM catchment_forcing "
            "WHERE reservoir_id = :rid AND date >= CURRENT_DATE - :w * INTERVAL '1 day' "
            "ORDER BY date"
        ),
        {"rid": rid, "w": window_days},
    ).fetchall()
    return [
        {"date": r.date, "precip_mm": None if r.precip_mm is None else float(r.precip_mm)}
        for r in rows
    ]
```

`api/src/api/routes.py`:

```python
@router.get("/reservoirs/{rid}/rainfall", response_model=list[RainfallPointOut])
def get_rainfall(
    rid: str, window: int = Query(default=90, ge=1, le=730), db: Session = Depends(get_db)
) -> list[dict]:
    _ensure_reservoir(db, rid)
    return repositories.rainfall(db, rid, window)
```

- [ ] **Step 4: Verify gates + commit**

Run: `uv run ruff check api tests && uv run mypy api && uv run pytest tests/unit tests/contract -q`

```bash
git add api tests/integration/test_api.py
git commit -m "feat(api): catchment rainfall endpoint (honest-empty until live forcing)"
```

---

### Task 5: Frontend foundation — deps, tokens, Zustand store (TDD with Vitest)

**Files:**
- Modify: `web/package.json` (deps + `test` script)
- Create: `web/src/styles/tokens.css`, `web/src/lib/store.ts`, `web/src/lib/store.test.ts`, `web/vitest.config.ts`

**Interfaces:**
- Produces: `useAppStore` Zustand hook with state `{view, selected, activeDate, playing}` and actions `selectReservoir(id)`, `openDashboard()`, `setActiveDate(d)`, `setPlaying(b)`; CSS custom properties (`--bg`, `--panel`, `--line`, `--text`, `--muted`, `--water`, `--water-deep`, `--warn`, `--ease-out`, `--dur-1/2/3`).

- [ ] **Step 1: Install dependencies**

```bash
cd web
npm install gsap @gsap/react zustand @tanstack/react-query
npm install -D vitest
```

- [ ] **Step 2: Add test script + vitest config**

`web/package.json` scripts: add `"test": "vitest run"`.

```ts
// web/vitest.config.ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
```

- [ ] **Step 3: Write the failing store tests** (the spec's 3 named transition cases)

```ts
// web/src/lib/store.test.ts
import { beforeEach, describe, expect, it } from "vitest";
import { useAppStore } from "./store";

const s = () => useAppStore.getState();

beforeEach(() => useAppStore.setState(useAppStore.getInitialState()));

describe("app store transitions", () => {
  it("selecting a reservoir enters map view and resets date/playing", () => {
    s().openDashboard();
    s().setActiveDate("2020-01-05");
    s().setPlaying(true);
    s().selectReservoir("pong");
    expect(s().view).toBe("map");
    expect(s().selected).toBe("pong");
    expect(s().activeDate).toBeNull(); // MapView sets it to latest acquisition
    expect(s().playing).toBe(false); // switching reservoir mid-play stops playback
  });

  it("opening dashboard stops playback but keeps selection", () => {
    s().selectReservoir("thein");
    s().setPlaying(true);
    s().openDashboard();
    expect(s().view).toBe("dashboard");
    expect(s().playing).toBe(false);
    expect(s().selected).toBe("thein");
  });

  it("setActiveDate ignores dates while no reservoir selected", () => {
    s().setActiveDate("2020-01-05");
    expect(s().activeDate).toBeNull();
  });
});
```

- [ ] **Step 4: Run to verify failure**

Run: `cd web && npx vitest run`
Expected: FAIL — cannot resolve `./store`.

- [ ] **Step 5: Implement the store**

```ts
// web/src/lib/store.ts
import { create } from "zustand";

export type ReservoirId = "gobind_sagar" | "pong" | "thein";
export type View = "map" | "dashboard";

interface AppState {
  view: View;
  selected: ReservoirId | null;
  activeDate: string | null;
  playing: boolean;
  selectReservoir: (id: ReservoirId) => void;
  openDashboard: () => void;
  setActiveDate: (d: string | null) => void;
  setPlaying: (p: boolean) => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  view: "map",
  selected: null,
  activeDate: null,
  playing: false,
  selectReservoir: (id) =>
    set({ view: "map", selected: id, activeDate: null, playing: false }),
  openDashboard: () => set({ view: "dashboard", playing: false }),
  setActiveDate: (d) => {
    if (get().selected !== null) set({ activeDate: d });
  },
  setPlaying: (p) => set({ playing: p }),
}));
```

- [ ] **Step 6: Create design tokens**

```css
/* web/src/styles/tokens.css — the entire design language in one file */
:root {
  --bg: #0d1117;
  --panel: #151b23;
  --panel-2: #1a222c;
  --line: #2a333e;
  --text: #dbe7f3;
  --muted: #71818f;
  --water: #59b7ff;
  --water-deep: #1f6db3;
  --warn: #e8b45a;
  --danger: #e0654f;
  --radius: 10px;
  --sidebar-w: 240px;
  --dock-h: 84px;
  --ease-out: cubic-bezier(0.22, 1, 0.36, 1);
  --dur-1: 200ms; /* micro */
  --dur-2: 450ms; /* panel */
  --dur-3: 1600ms; /* camera */
  --font: "Segoe UI", system-ui, -apple-system, sans-serif;
  --mono: ui-monospace, "Cascadia Code", monospace;
}
```

Import it first in `web/src/main.tsx`: `import "./styles/tokens.css";`

- [ ] **Step 7: Verify + commit**

Run: `cd web && npx vitest run && npm run build`
Expected: 3 tests pass; build clean.

```bash
git add web/package.json web/package-lock.json web/vitest.config.ts web/src/lib/store.ts web/src/lib/store.test.ts web/src/styles/tokens.css web/src/main.tsx
git commit -m "feat(web): animated-app foundation — gsap/zustand/query deps, tokens, tested store"
```

---

### Task 6: Typed API client + TanStack Query hooks

**Files:**
- Create: `web/src/lib/api.ts`, `web/src/lib/queries.ts`
- Modify: `web/src/types.ts` (append), `web/src/main.tsx` (QueryClientProvider)

**Interfaces:**
- Consumes: endpoints from Tasks 2–4 + existing `/reservoirs`, `/reservoirs/{id}/status`, `/geojson/reservoirs`, `/geojson/aoi`.
- Produces: hooks `useAcquisitions(rid)`, `useSarTile(rid, date)`, `useRainfall(rid)`, `useStatus(rid)`, `useMarkers()`, `useAoi()`. `useSarTile` retries never on 503 and exposes `error` for the fallback chip.

- [ ] **Step 1: Add types** (append to `web/src/types.ts`)

```ts
export interface Acquisition {
  date: string;
  area_km2: number;
  confidence: number;
}
export interface SarTile {
  tile_url: string;
  expires_at: string;
}
export interface RainfallPoint {
  date: string;
  precip_mm: number | null;
}
```

- [ ] **Step 2: Write the client** (preserves the remediation's abort-safety; keep the old file until Task 11 deletes it)

```ts
// web/src/lib/api.ts
const BASE = "/api";

export class ApiError extends Error {
  constructor(public status: number, public url: string) {
    super(`${url} -> ${status}`);
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { signal });
  if (!res.ok) throw new ApiError(res.status, path);
  return (await res.json()) as T;
}

export const api = {
  reservoirs: (s?: AbortSignal) => getJson<import("../types").Reservoir[]>("/reservoirs", s),
  status: (rid: string, s?: AbortSignal) =>
    getJson<import("../types").ReservoirStatus>(`/reservoirs/${rid}/status`, s),
  acquisitions: (rid: string, s?: AbortSignal) =>
    getJson<import("../types").Acquisition[]>(`/reservoirs/${rid}/acquisitions`, s),
  sarTile: (rid: string, date: string, s?: AbortSignal) =>
    getJson<import("../types").SarTile>(`/reservoirs/${rid}/sar-tiles?date=${date}`, s),
  rainfall: (rid: string, s?: AbortSignal) =>
    getJson<import("../types").RainfallPoint[]>(`/reservoirs/${rid}/rainfall?window=90`, s),
  markers: (s?: AbortSignal) => getJson<import("../types").GeoFC>("/geojson/reservoirs", s),
  aoi: (s?: AbortSignal) => getJson<import("../types").GeoFC>("/geojson/aoi", s),
};
```

Check `web/src/types.ts` for the exact existing names `Reservoir`, `ReservoirStatus`, `GeoFC` — they exist from the current app; keep them.

- [ ] **Step 3: Write the hooks**

```ts
// web/src/lib/queries.ts
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "./api";

export const useMarkers = () =>
  useQuery({ queryKey: ["markers"], queryFn: ({ signal }) => api.markers(signal) });

export const useAoi = () =>
  useQuery({ queryKey: ["aoi"], queryFn: ({ signal }) => api.aoi(signal), staleTime: Infinity });

export const useStatus = (rid: string | null) =>
  useQuery({
    queryKey: ["status", rid],
    queryFn: ({ signal }) => api.status(rid!, signal),
    enabled: rid !== null,
    refetchInterval: 90_000,
  });

export const useAcquisitions = (rid: string | null) =>
  useQuery({
    queryKey: ["acquisitions", rid],
    queryFn: ({ signal }) => api.acquisitions(rid!, signal),
    enabled: rid !== null,
    staleTime: 10 * 60_000,
  });

export const useSarTile = (rid: string | null, date: string | null) =>
  useQuery({
    queryKey: ["sarTile", rid, date],
    queryFn: ({ signal }) => api.sarTile(rid!, date!, signal),
    enabled: rid !== null && date !== null,
    staleTime: 3 * 60 * 60_000, // matches server TTL
    retry: (count, err) => !(err instanceof ApiError && err.status === 503) && count < 2,
  });

export const useRainfall = (rid: string | null) =>
  useQuery({
    queryKey: ["rainfall", rid],
    queryFn: ({ signal }) => api.rainfall(rid!, signal),
    enabled: rid !== null,
  });
```

- [ ] **Step 4: Wire the provider** in `web/src/main.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
const queryClient = new QueryClient();
// wrap: <QueryClientProvider client={queryClient}><App /></QueryClientProvider>
```

- [ ] **Step 5: Verify + commit**

Run: `cd web && npm run build`
Expected: clean (new modules compile; old app still uses old `web/src/api.ts` — both exist until Task 11).

```bash
git add web/src/lib/api.ts web/src/lib/queries.ts web/src/types.ts web/src/main.tsx
git commit -m "feat(web): typed client + TanStack Query hooks for the new endpoints"
```

---

### Task 7: Shell — App, Sidebar, ReservoirButton, motion module seed

**Files:**
- Create: `web/src/lib/motion.ts`, `web/src/components/Sidebar.tsx`, `web/src/components/ReservoirButton.tsx`, `web/src/components/stage/MapView.tsx` (placeholder), `web/src/components/stage/DashboardView.tsx` (placeholder)
- Modify: `web/src/App.tsx` (full rewrite), `web/src/styles.css` (replace layout styles)

**Interfaces:**
- Consumes: `useAppStore`, `useStatus`.
- Produces: shell layout; `motion.ts` exports `appLoadIn(root: HTMLElement)`, `viewSwap(stage: HTMLElement, entering: 'map'|'dashboard')`, `countTo(el: HTMLElement, value: number, decimals?: number)`, `meterTo(fillEl: HTMLElement, fraction: number)`, `dockRise(el: HTMLElement)`, `buttonSweep(el: HTMLElement)` — later tasks call these exact names.

- [ ] **Step 1: Seed the motion module** (ALL gsap timelines live here — spec requirement)

```ts
// web/src/lib/motion.ts
import gsap from "gsap";

/** App load: sidebar slides in, buttons stagger, stage fades from black. */
export function appLoadIn(root: HTMLElement) {
  const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
  tl.from(root.querySelector(".sidebar"), { x: -40, opacity: 0, duration: 0.5 })
    .from(root.querySelectorAll(".rbtn, .dbtn"), { y: 14, opacity: 0, stagger: 0.08 }, "-=0.2")
    .from(root.querySelector(".stage"), { opacity: 0, duration: 0.9 }, "-=0.3");
  return tl;
}

/** View swap: outgoing scales back + dims, incoming fades/rises. */
export function viewSwap(stage: HTMLElement, entering: "map" | "dashboard") {
  const tl = gsap.timeline({ defaults: { ease: "power2.inOut" } });
  tl.fromTo(stage, { opacity: 0.25, scale: entering === "dashboard" ? 1.02 : 0.98 },
    { opacity: 1, scale: 1, duration: 0.45 });
  return tl;
}

/** Numbers count, never snap. */
export function countTo(el: HTMLElement, value: number, decimals = 1) {
  const obj = { v: parseFloat(el.textContent ?? "0") || 0 };
  return gsap.to(obj, {
    v: value, duration: 0.8, ease: "power1.out",
    onUpdate: () => { el.textContent = obj.v.toFixed(decimals); },
  });
}

/** Vertical meter eases to a 0..1 fraction. */
export function meterTo(fillEl: HTMLElement, fraction: number) {
  return gsap.to(fillEl, { height: `${Math.max(0, Math.min(1, fraction)) * 100}%`,
    duration: 0.7, ease: "power2.out" });
}

/** Timeline dock rises from the bottom edge. */
export function dockRise(el: HTMLElement) {
  return gsap.from(el, { yPercent: 110, duration: 0.55, ease: "power3.out" });
}

/** Highlight sweep across a clicked reservoir button. */
export function buttonSweep(el: HTMLElement) {
  const sweep = document.createElement("div");
  sweep.className = "sweep";
  el.appendChild(sweep);
  return gsap.fromTo(sweep, { xPercent: -110 }, {
    xPercent: 110, duration: 0.6, ease: "power2.out",
    onComplete: () => sweep.remove(),
  });
}
```

- [ ] **Step 2: Rewrite App.tsx as shell-only**

```tsx
// web/src/App.tsx
import { useEffect, useRef } from "react";
import { useAppStore } from "./lib/store";
import { appLoadIn, viewSwap } from "./lib/motion";
import Sidebar from "./components/Sidebar";
import MapView from "./components/stage/MapView";
import DashboardView from "./components/stage/DashboardView";

export default function App() {
  const view = useAppStore((s) => s.view);
  const rootRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (rootRef.current) appLoadIn(rootRef.current);
  }, []);

  useEffect(() => {
    if (stageRef.current) viewSwap(stageRef.current, view);
  }, [view]);

  return (
    <div className="app" ref={rootRef}>
      <Sidebar />
      <div className="stage" ref={stageRef}>
        {view === "map" ? <MapView /> : <DashboardView />}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Sidebar + ReservoirButton**

```tsx
// web/src/components/Sidebar.tsx
import { useAppStore } from "../lib/store";
import ReservoirButton from "./ReservoirButton";

const RESERVOIRS = [
  { id: "gobind_sagar", name: "Gobind Sagar", basin: "Sutlej" },
  { id: "pong", name: "Pong Dam", basin: "Beas" },
  { id: "thein", name: "Thein Dam", basin: "Ravi" },
] as const;

export default function Sidebar() {
  const view = useAppStore((s) => s.view);
  const openDashboard = useAppStore((s) => s.openDashboard);
  return (
    <nav className="sidebar">
      <div className="brand">◈ RESERVOIR WATCH</div>
      {RESERVOIRS.map((r) => (
        <ReservoirButton key={r.id} id={r.id} name={r.name} basin={r.basin} />
      ))}
      <button
        className={`dbtn ${view === "dashboard" ? "active" : ""}`}
        onClick={openDashboard}
      >
        ▦ Dashboard
      </button>
    </nav>
  );
}
```

```tsx
// web/src/components/ReservoirButton.tsx
import { useEffect, useRef } from "react";
import { useAppStore, type ReservoirId } from "../lib/store";
import { useStatus } from "../lib/queries";
import { buttonSweep, countTo } from "../lib/motion";

export default function ReservoirButton(props: {
  id: ReservoirId; name: string; basin: string;
}) {
  const selected = useAppStore((s) => s.selected);
  const view = useAppStore((s) => s.view);
  const selectReservoir = useAppStore((s) => s.selectReservoir);
  const { data: status } = useStatus(props.id);
  const ref = useRef<HTMLButtonElement>(null);
  const fillRef = useRef<HTMLSpanElement>(null);
  const active = view === "map" && selected === props.id;

  useEffect(() => {
    if (fillRef.current && status?.pct_filled != null)
      countTo(fillRef.current, Number(status.pct_filled), 1);
  }, [status?.pct_filled]);

  return (
    <button
      ref={ref}
      className={`rbtn ${active ? "active" : ""}`}
      onClick={() => {
        selectReservoir(props.id);
        if (ref.current) buttonSweep(ref.current);
      }}
    >
      <span className="rbtn-name">{props.name}</span>
      <span className="rbtn-sub">
        {props.basin} · <span ref={fillRef}>—</span>%
      </span>
    </button>
  );
}
```

Check `web/src/types.ts` `ReservoirStatus` for the exact fill field name (`pct_filled` in the current app) and adjust if it differs.

- [ ] **Step 4: Placeholder stage views** (replaced in Tasks 8/10)

```tsx
// web/src/components/stage/MapView.tsx
export default function MapView() {
  return <div className="mapview">map coming in Task 8</div>;
}
```

```tsx
// web/src/components/stage/DashboardView.tsx
export default function DashboardView() {
  return <div className="dashview">dashboard coming in Task 10</div>;
}
```

- [ ] **Step 5: Replace layout CSS** (rewrite `web/src/styles.css` top section; keep any chart styles used later)

```css
@import "./styles/tokens.css";

* { box-sizing: border-box; }
html, body, #root { height: 100%; margin: 0; }
body { background: var(--bg); color: var(--text); font-family: var(--font); }

.app { display: flex; height: 100%; overflow: hidden; }
.sidebar {
  width: var(--sidebar-w); flex: none; background: var(--panel);
  border-right: 1px solid var(--line); display: flex; flex-direction: column;
  gap: 8px; padding: 14px 10px; z-index: 1000; position: relative;
}
.brand { font-size: 12px; font-weight: 700; letter-spacing: 2px; padding: 4px 8px 12px; }
.rbtn {
  position: relative; overflow: hidden; text-align: left; cursor: pointer;
  background: var(--panel-2); color: var(--text); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 10px 12px;
  transition: border-color var(--dur-1) var(--ease-out);
}
.rbtn:hover { border-color: var(--water-deep); }
.rbtn.active { background: #12314a; border-color: var(--water); }
.rbtn-name { display: block; font-size: 13px; font-weight: 600; }
.rbtn-sub { display: block; font-size: 11px; color: var(--muted); margin-top: 2px; }
.sweep {
  position: absolute; inset: 0;
  background: linear-gradient(105deg, transparent 30%, rgba(89,183,255,.25) 50%, transparent 70%);
  pointer-events: none;
}
.dbtn {
  margin-top: auto; cursor: pointer; font-weight: 700; font-size: 13px;
  color: #0e1116; background: var(--water); border: none;
  border-radius: var(--radius); padding: 11px 12px;
}
.dbtn.active { outline: 2px solid var(--text); }
.stage { flex: 1; position: relative; min-width: 0; }
.mapview, .dashview { position: absolute; inset: 0; }
```

- [ ] **Step 6: Verify + commit**

Run: `cd web && npm run build && npx vitest run`
Expected: clean build, store tests still pass. Then run `cd web && npm run dev` and eyeball: sidebar slides in, buttons stagger, clicking a button sweeps + activates, Dashboard button swaps the stage placeholder.

```bash
git add web/src
git commit -m "feat(web): shell — sidebar, reservoir buttons, motion module, view swap"
```

---

### Task 8: MapView — Leaflet, flyTo, AOI outline, SAR tile crossfade

**Files:**
- Rewrite: `web/src/components/stage/MapView.tsx`
- Create: `web/src/components/stage/SarTileLayer.tsx`
- Modify: `web/src/styles.css` (append map styles)

**Interfaces:**
- Consumes: `useAppStore`, `useMarkers`, `useAoi`, `useAcquisitions`, `useSarTile`, `motion.dockRise` (Task 9 renders the dock inside MapView's container).
- Produces: `<MapView/>` renders full-bleed map; sets `activeDate` to the latest acquisition when a reservoir is selected and `activeDate === null`; `<SarTileLayer rid date/>` crossfades EE tiles; exposes CSS classes `.imagery-chip` for the 503 fallback.

- [ ] **Step 1: Implement SarTileLayer** (two stacked native Leaflet tile layers; GSAP fades the incoming one)

```tsx
// web/src/components/stage/SarTileLayer.tsx
import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import gsap from "gsap";
import { useSarTile } from "../../lib/queries";
import type { ReservoirId } from "../../lib/store";

/** Crossfading Sentinel-1 tile pair: on each date change the new layer fades in
 *  over the old one, then the old layer is removed (spec: scrub crossfade 300ms). */
export default function SarTileLayer(props: { rid: ReservoirId; date: string | null }) {
  const map = useMap();
  const currentRef = useRef<L.TileLayer | null>(null);
  const { data, error } = useSarTile(props.rid, props.date);

  useEffect(() => {
    if (!data?.tile_url) return;
    const next = L.tileLayer(data.tile_url, { opacity: 0, maxZoom: 14, pane: "overlayPane" });
    next.addTo(map);
    const prev = currentRef.current;
    currentRef.current = next;
    const state = { o: 0 };
    const tween = gsap.to(state, {
      o: 0.85, duration: 0.3, ease: "power1.inOut",
      onUpdate: () => next.setOpacity(state.o),
      onComplete: () => { if (prev) map.removeLayer(prev); },
    });
    return () => { tween.kill(); };
  }, [data?.tile_url, map]);

  useEffect(() => () => { // unmount: drop any live layer
    if (currentRef.current) map.removeLayer(currentRef.current);
  }, [map]);

  if (error) return <div className="imagery-chip">⚠ live imagery unavailable</div>;
  return null;
}
```

- [ ] **Step 2: Rewrite MapView**

```tsx
// web/src/components/stage/MapView.tsx
import { useEffect } from "react";
import { MapContainer, TileLayer, GeoJSON, CircleMarker, useMap } from "react-leaflet";
import { useAppStore } from "../../lib/store";
import { useAcquisitions, useAoi, useMarkers } from "../../lib/queries";
import SarTileLayer from "./SarTileLayer";
import TimelineDock from "./TimelineDock";
import AreaMeter from "./AreaMeter";

const HOME: [number, number] = [31.9, 76.1];

/** Eased camera: flies to the selected reservoir marker (spec motion score). */
function CameraDriver() {
  const map = useMap();
  const selected = useAppStore((s) => s.selected);
  const { data: markers } = useMarkers();
  useEffect(() => {
    if (!selected || !markers) return;
    const f = markers.features.find((f) => f.properties?.reservoir_id === selected);
    if (!f) return;
    const [lon, lat] = (f.geometry as { coordinates: [number, number] }).coordinates;
    map.flyTo([lat, lon], 11, { duration: 1.8, easeLinearity: 0.18 });
  }, [selected, markers, map]);
  return null;
}

export default function MapView() {
  const selected = useAppStore((s) => s.selected);
  const activeDate = useAppStore((s) => s.activeDate);
  const setActiveDate = useAppStore((s) => s.setActiveDate);
  const { data: aoi } = useAoi();
  const { data: markers } = useMarkers();
  const { data: acqs } = useAcquisitions(selected);

  // default the timeline to the latest acquisition on reservoir switch
  useEffect(() => {
    if (selected && acqs?.length && activeDate === null)
      setActiveDate(acqs[acqs.length - 1]!.date);
  }, [selected, acqs, activeDate, setActiveDate]);

  return (
    <div className="mapview">
      <MapContainer center={HOME} zoom={8} zoomControl={false} className="leaflet-root">
        <TileLayer
          url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
          attribution="Esri"
        />
        <CameraDriver />
        {aoi && <GeoJSON key={`aoi-${aoi.features.length}`} data={aoi}
          style={{ color: "#59b7ff", weight: 1.5, fillOpacity: 0.05 }} />}
        {markers?.features.map((f) => {
          const [lon, lat] = (f.geometry as { coordinates: [number, number] }).coordinates;
          const id = f.properties?.reservoir_id as string;
          return <CircleMarker key={id} center={[lat, lon]} radius={8}
            pathOptions={{ color: "#dff0ff", fillColor: "#59b7ff", fillOpacity: 0.9 }} />;
        })}
        {selected && activeDate && <SarTileLayer rid={selected} date={activeDate} />}
      </MapContainer>
      {selected && acqs && <AreaMeter acquisitions={acqs} />}
      {selected && acqs && <TimelineDock acquisitions={acqs} />}
    </div>
  );
}
```

- [ ] **Step 3: Append map styles**

```css
.leaflet-root { position: absolute; inset: 0; background: #05080a; }
.imagery-chip {
  position: absolute; top: 12px; right: 12px; z-index: 1100;
  background: rgba(21,27,35,.9); border: 1px solid var(--warn); color: var(--warn);
  font-size: 11px; padding: 6px 10px; border-radius: 16px;
}
```

Also create stub files so this task builds (implemented next tasks):

```tsx
// web/src/components/stage/TimelineDock.tsx (stub — Task 9 replaces)
import type { Acquisition } from "../../types";
export default function TimelineDock(_props: { acquisitions: Acquisition[] }) { return null; }
```

```tsx
// web/src/components/stage/AreaMeter.tsx (stub — Task 9 replaces)
import type { Acquisition } from "../../types";
export default function AreaMeter(_props: { acquisitions: Acquisition[] }) { return null; }
```

- [ ] **Step 4: Verify + commit**

Run: `cd web && npm run build` — clean. Dev-run: map fills the stage; clicking a reservoir flies the camera; with the API+DB up and GEE key present, the latest SAR scene fades in; without GEE the amber chip appears.

```bash
git add web/src
git commit -m "feat(web): fullscreen map — eased flyTo, AOI outline, SAR tile crossfade"
```

---

### Task 9: TimelineDock (sparkline + scrub + play) and AreaMeter

**Files:**
- Rewrite: `web/src/components/stage/TimelineDock.tsx`, `web/src/components/stage/AreaMeter.tsx`
- Modify: `web/src/styles.css` (append), `web/src/lib/motion.ts` (no changes — uses `dockRise`, `meterTo`, `countTo`)

**Interfaces:**
- Consumes: `acquisitions: Acquisition[]` prop, `useAppStore` (`activeDate`, `setActiveDate`, `playing`, `setPlaying`), motion fns from Task 7.
- Produces: docked scrubber that snaps to acquisition dates (abstained dates are simply absent from the list — gaps render as sparkline discontinuities); play mode advances ~600 ms/step and stops at the end.

- [ ] **Step 1: Implement TimelineDock**

```tsx
// web/src/components/stage/TimelineDock.tsx
import { useEffect, useMemo, useRef } from "react";
import { useAppStore } from "../../lib/store";
import { dockRise } from "../../lib/motion";
import type { Acquisition } from "../../types";

export default function TimelineDock({ acquisitions }: { acquisitions: Acquisition[] }) {
  const activeDate = useAppStore((s) => s.activeDate);
  const setActiveDate = useAppStore((s) => s.setActiveDate);
  const playing = useAppStore((s) => s.playing);
  const setPlaying = useAppStore((s) => s.setPlaying);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => { if (rootRef.current) dockRise(rootRef.current); }, []);

  const idx = useMemo(
    () => Math.max(0, acquisitions.findIndex((a) => a.date === activeDate)),
    [acquisitions, activeDate],
  );

  // play mode: advance ~600ms/step, stop at the end (spec motion score)
  useEffect(() => {
    if (!playing) return;
    const t = window.setInterval(() => {
      const next = acquisitions[idx + 1];
      if (next) setActiveDate(next.date);
      else setPlaying(false);
    }, 600);
    return () => window.clearInterval(t);
  }, [playing, idx, acquisitions, setActiveDate, setPlaying]);

  const max = Math.max(...acquisitions.map((a) => a.area_km2));
  const min = Math.min(...acquisitions.map((a) => a.area_km2));
  const points = acquisitions
    .map((a, i) => {
      const x = (i / (acquisitions.length - 1)) * 100;
      const y = 100 - ((a.area_km2 - min) / (max - min || 1)) * 100;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <div className="dock" ref={rootRef}>
      <svg className="dock-spark" viewBox="0 0 100 100" preserveAspectRatio="none">
        <polyline points={points} fill="none" stroke="var(--water)" strokeWidth="1"
          vectorEffect="non-scaling-stroke" />
        <line x1={(idx / (acquisitions.length - 1)) * 100} y1="0"
          x2={(idx / (acquisitions.length - 1)) * 100} y2="100"
          stroke="var(--text)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="dock-controls">
        <button className="playbtn" onClick={() => setPlaying(!playing)}>
          {playing ? "❚❚" : "▶"}
        </button>
        <input
          type="range" min={0} max={acquisitions.length - 1} value={idx}
          onChange={(e) => setActiveDate(acquisitions[Number(e.target.value)]!.date)}
        />
        <span className="dock-date">{activeDate ?? "—"}</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Implement AreaMeter**

```tsx
// web/src/components/stage/AreaMeter.tsx
import { useEffect, useMemo, useRef } from "react";
import gsap from "gsap";
import { useAppStore } from "../../lib/store";
import { countTo, meterTo } from "../../lib/motion";
import type { Acquisition } from "../../types";

export default function AreaMeter({ acquisitions }: { acquisitions: Acquisition[] }) {
  const activeDate = useAppStore((s) => s.activeDate);
  const fillRef = useRef<HTMLDivElement>(null);
  const numRef = useRef<HTMLDivElement>(null);

  const { min, max } = useMemo(() => ({
    min: Math.min(...acquisitions.map((a) => a.area_km2)),
    max: Math.max(...acquisitions.map((a) => a.area_km2)),
  }), [acquisitions]);
  const active = acquisitions.find((a) => a.date === activeDate);

  useEffect(() => {
    if (!active || !fillRef.current || !numRef.current) return;
    meterTo(fillRef.current, (active.area_km2 - min) / (max - min || 1));
    countTo(numRef.current, active.area_km2, 1);
  }, [active, min, max]);

  // idle shimmer: slow sine on the fill's gradient position (spec motion score)
  useEffect(() => {
    if (!fillRef.current) return;
    const tween = gsap.to(fillRef.current, {
      backgroundPosition: "0 12px", duration: 2.4, yoyo: true, repeat: -1,
      ease: "sine.inOut",
    });
    return () => { tween.kill(); };
  }, []);

  return (
    <div className="meter">
      <div className="meter-label">km²</div>
      <div className="meter-tube">
        <div className="meter-fill" ref={fillRef} />
      </div>
      <div className="meter-num" ref={numRef}>—</div>
      <div className="meter-minmax">{min.toFixed(0)}–{max.toFixed(0)}</div>
    </div>
  );
}
```

- [ ] **Step 3: Append styles**

```css
.dock {
  position: absolute; left: 0; right: 0; bottom: 0; height: var(--dock-h);
  z-index: 1050; background: rgba(13,18,23,.92); border-top: 1px solid var(--line);
  padding: 8px 16px; backdrop-filter: blur(4px);
}
.dock-spark { width: 100%; height: 30px; display: block; }
.dock-controls { display: flex; align-items: center; gap: 12px; margin-top: 6px; }
.dock-controls input[type="range"] { flex: 1; accent-color: var(--water); }
.playbtn {
  cursor: pointer; width: 30px; height: 30px; border-radius: 50%;
  border: 1px solid var(--line); background: var(--panel-2); color: var(--text);
}
.dock-date { font-family: var(--mono); font-size: 12px; color: var(--text); min-width: 86px; }
.meter {
  position: absolute; top: 6%; right: 16px; z-index: 1050; width: 44px;
  display: flex; flex-direction: column; align-items: center; gap: 6px;
}
.meter-label { font-size: 9px; color: var(--muted); letter-spacing: 1px; }
.meter-tube {
  width: 30px; height: 46vh; background: var(--panel);
  border: 1px solid var(--line); border-radius: 8px; overflow: hidden;
  display: flex; align-items: flex-end;
}
.meter-fill {
  width: 100%; height: 0%;
  background: linear-gradient(180deg, var(--water), var(--water-deep));
  background-size: 100% 200%;
}
.meter-num { font-size: 13px; font-weight: 700; font-family: var(--mono); }
.meter-minmax { font-size: 9px; color: var(--muted); }
```

- [ ] **Step 4: Verify + commit**

Run: `cd web && npm run build && npx vitest run` — clean. Dev-run with API up: scrub the slider (tiles crossfade, meter eases, number counts); press play (auto-advance, stops at end); switch reservoir mid-play (playback stops — the store test guarantees it).

```bash
git add web/src
git commit -m "feat(web): sparkline timeline dock with play mode + animated area meter"
```

---

### Task 10: DashboardView — fleet analytics grid

**Files:**
- Rewrite: `web/src/components/stage/DashboardView.tsx`
- Modify: `web/src/styles.css` (append), `web/src/lib/motion.ts` (add `panelsIn`)

**Interfaces:**
- Consumes: `useAcquisitions` per reservoir, `useStatus` per reservoir, `useRainfall(selected ?? 'gobind_sagar')`.
- Produces: dashboard grid: all-reservoir SAR area chart (Recharts), fill/level cards, rainfall panel with the "awaiting live forcing" empty state.

- [ ] **Step 1: Add `panelsIn` to motion.ts**

```ts
/** Dashboard panels stagger in with a 60ms cascade (spec motion score). */
export function panelsIn(root: HTMLElement) {
  return gsap.from(root.querySelectorAll(".panel"), {
    y: 18, opacity: 0, stagger: 0.06, duration: 0.45, ease: "power3.out",
  });
}
```

- [ ] **Step 2: Implement DashboardView**

```tsx
// web/src/components/stage/DashboardView.tsx
import { useEffect, useRef } from "react";
import {
  Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid,
} from "recharts";
import { useAcquisitions, useRainfall, useStatus } from "../../lib/queries";
import { panelsIn } from "../../lib/motion";
import type { ReservoirId } from "../../lib/store";

const IDS: ReservoirId[] = ["gobind_sagar", "pong", "thein"];
const NAMES = { gobind_sagar: "Gobind Sagar", pong: "Pong", thein: "Thein" } as const;
const COLORS = { gobind_sagar: "#59b7ff", pong: "#7ee2a8", thein: "#e8b45a" } as const;

export default function DashboardView() {
  const rootRef = useRef<HTMLDivElement>(null);
  const gob = useAcquisitions("gobind_sagar");
  const pon = useAcquisitions("pong");
  const the = useAcquisitions("thein");
  const statuses = { gobind_sagar: useStatus("gobind_sagar"), pong: useStatus("pong"), thein: useStatus("thein") };
  const rain = useRainfall("gobind_sagar");

  useEffect(() => { if (rootRef.current) panelsIn(rootRef.current); }, []);

  // merge the three series onto one date axis for the fleet chart
  const byDate = new Map<string, Record<string, number | string>>();
  for (const [id, q] of [["gobind_sagar", gob], ["pong", pon], ["thein", the]] as const) {
    for (const a of q.data ?? []) {
      const row = byDate.get(a.date) ?? { date: a.date };
      row[id] = a.area_km2;
      byDate.set(a.date, row);
    }
  }
  const fleet = [...byDate.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)));

  return (
    <div className="dashview" ref={rootRef}>
      <div className="panel panel-wide">
        <div className="panel-title">SURFACE AREA — SAR, ALL RESERVOIRS</div>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={fleet}>
            <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" />
            <XAxis dataKey="date" stroke="var(--muted)" fontSize={10} minTickGap={60} />
            <YAxis stroke="var(--muted)" fontSize={10} unit=" km²" />
            <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)" }} />
            {IDS.map((id) => (
              <Line key={id} dataKey={id} name={NAMES[id]} stroke={COLORS[id]}
                dot={false} strokeWidth={1.5} connectNulls />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {IDS.map((id) => {
        const s = statuses[id].data;
        return (
          <div className="panel" key={id}>
            <div className="panel-title">{NAMES[id].toUpperCase()}</div>
            <div className="kpi-big">{s ? Number(s.pct_filled).toFixed(1) : "—"}<small>% fill</small></div>
            <div className="kpi-sub">
              level {s ? Number(s.current_level_m).toFixed(1) : "—"} m ·{" "}
              {s ? Number(s.live_storage_bcm).toFixed(2) : "—"} BCM
            </div>
          </div>
        );
      })}
      <div className="panel panel-wide">
        <div className="panel-title">CATCHMENT RAINFALL — 90 D</div>
        {rain.data && rain.data.length > 0 ? (
          <ResponsiveContainer width="100%" height={120}>
            <LineChart data={rain.data}>
              <XAxis dataKey="date" stroke="var(--muted)" fontSize={10} minTickGap={60} />
              <YAxis stroke="var(--muted)" fontSize={10} unit=" mm" />
              <Line dataKey="precip_mm" stroke="var(--water)" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="empty-state">awaiting live forcing ingest — no rainfall data yet</div>
        )}
      </div>
    </div>
  );
}
```

Check `web/src/types.ts` `ReservoirStatus` for exact field names (`pct_filled`, `current_level_m`, `live_storage_bcm` per the current app) — adjust to match.

- [ ] **Step 3: Append styles**

```css
.dashview {
  position: absolute; inset: 0; overflow-y: auto; padding: 16px;
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px;
  align-content: start; background: var(--bg);
}
.panel {
  background: var(--panel); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 12px 14px;
}
.panel-wide { grid-column: 1 / -1; }
.panel-title { font-size: 10px; letter-spacing: 1.5px; color: var(--muted); margin-bottom: 8px; }
.kpi-big { font-size: 30px; font-weight: 700; }
.kpi-big small { font-size: 12px; color: var(--muted); margin-left: 4px; }
.kpi-sub { font-size: 12px; color: var(--muted); margin-top: 4px; }
.empty-state { color: var(--muted); font-size: 12px; padding: 24px 0; text-align: center; }
```

- [ ] **Step 4: Verify + commit**

Run: `cd web && npm run build && npx vitest run` — clean.

```bash
git add web/src
git commit -m "feat(web): fleet analytics dashboard with staggered panels + honest rainfall state"
```

---

### Task 11: Cleanup — delete the old app surface

**Files:**
- Delete: `web/src/api.ts`, `web/src/components/ReservoirMap.tsx`, `web/src/components/TrendChart.tsx`, `web/src/components/ForecastChart.tsx`
- Modify: `web/src/styles.css` (remove any now-unreferenced legacy classes), `web/src/types.ts` (remove types only the deleted files used — keep `Reservoir`, `ReservoirStatus`, `GeoFC`, and everything `lib/` imports)

- [ ] **Step 1: Delete and prune**

```bash
git rm web/src/api.ts web/src/components/ReservoirMap.tsx web/src/components/TrendChart.tsx web/src/components/ForecastChart.tsx
```

Then `cd web && npm run build` and fix every resulting "cannot find module / unused" error by removing the dead import/type — the compiler is the checklist. Forecast/risk types stay in `types.ts` only if still referenced; otherwise delete (Phase-1 rescope keeps that UI dormant — it is regrown from the API later, not from dead frontend code).

- [ ] **Step 2: Verify + commit**

Run: `cd web && npm run build && npx vitest run` — clean, no unused-export noise.

```bash
git add web
git commit -m "chore(web): remove superseded two-pane app surface"
```

---

### Task 12: Manual smoke pass + docs

**Files:**
- Create: `docs/runbooks/dashboard-smoke.md`
- Modify: `README.md` (one line: dashboard description)

- [ ] **Step 1: Write the smoke script**

```markdown
# Dashboard smoke pass (manual, ~5 min)

Prereq: `start.bat` (stack up, migrated, backfill loaded via
`uv run python scripts/load_backfill.py`), GEE key present.

1. Load app → sidebar slides in, buttons stagger, map fades from black.
2. Click Gobind Sagar → camera flies in (~1.8 s), timeline dock rises,
   meter fills, latest SAR scene fades onto the map.
3. Scrub the slider → tiles crossfade ~300 ms, meter eases, date ticks,
   number counts (never snaps).
4. Press ▶ → auto-advance ~600 ms/step; press again to pause; let it reach
   the end → playback stops by itself.
5. Switch to Pong mid-play → playback stops, camera flies, dock reloads.
6. Click Dashboard → map view swaps out, panels stagger in with cascade,
   fleet chart draws; rainfall panel shows "awaiting live forcing".
7. Stop the API (`docker compose stop api`) → per-source failures degrade
   (chips/empty states), no blank screen.
8. Remove/rename the GEE key, restart API, pick a date → amber
   "live imagery unavailable" chip; basemap + AOI outline still render.
```

- [ ] **Step 2: Run the smoke pass yourself** (requires Docker + DB + loaded backfill). Record any failures as fixes before committing.

- [ ] **Step 3: Commit**

```bash
git add docs/runbooks/dashboard-smoke.md README.md
git commit -m "docs: dashboard smoke runbook + README note"
```

---

## Self-review (performed at write time)

- **Spec coverage:** endpoints 1/2/3 → Tasks 2/3/4; loader prerequisite → Task 1; store/state → Task 5; query caching → Task 6; shell + motion module → Task 7; map/flyTo/crossfade/fallback chip → Task 8; timeline + play + meter + shimmer → Task 9; dashboard + stagger + honest rainfall → Task 10; old-surface removal → Task 11; manual motion verification → Task 12. Abstained-date honesty: abstains are never loaded (Task 1), so gaps are structural; sparkline discontinuities render them (Task 9).
- **Placeholder scan:** one deliberate verify-then-substitute (`<PRECIP_COL>`, Task 4 Step 1 resolves it against the model) and three "check the existing name" steps (fixtures, status fields, `_ensure_reservoir`) — each has an exact command and a fallback rule; no TBDs.
- **Type consistency:** `Acquisition {date, area_km2, confidence}` used identically in Tasks 2/6/9/10; motion fn names (`dockRise`, `meterTo`, `countTo`, `panelsIn`, `buttonSweep`, `viewSwap`, `appLoadIn`) defined Task 7/10 and consumed with the same names; store actions consistent across Tasks 5/7/8/9.
