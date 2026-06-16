# 01 — Infrastructure & Platform Implementation Plan

**Owner:** Platform / DevOps
**Status:** Draft for review
**Spec version targeted:** requirements.md v1.2 (2026-06-16)
**Scope class:** Planning only — no application code in this document.

This plan establishes the *substrate* every other team builds on: the monorepo,
the `uv` workspace, the container topology, secrets/config, CI gates, observability,
backups, the GEE-auth + swappable data-access abstraction, and the
graceful-degradation/staleness plumbing. It deliberately stops at the seams where
other teams own the logic (remote-sensing, data-engineering, ML, API handlers, web
components) and instead defines the *contracts* those teams plug into.

---

## 1. Scope & owned requirements

I own the infrastructure realisation of these requirement areas. IDs are cited so
reviewers can trace coverage.

| Area | Requirement IDs | What I own here |
| --- | --- | --- |
| Mandated stack & topology | §4.2, §4.3 | Compose services, images, service wiring, orchestrator (Prefect 2) host |
| Open-source / free-data constraint | §4.4 | No paid services in infra; GEE non-commercial auth; swappable data-access layer |
| Scalability | NFR-SCALE-1, NFR-SCALE-2 | Stateless API, horizontally scalable pipeline workers, config-driven fleet |
| Reliability & observability | NFR-REL-1..6 | Retry/backoff plumbing, structured logging, health endpoints, run-history store, audit-trail storage, **graceful degradation / staleness** |
| DB backups | NFR-REL-4 | Automated `pg_dump` + WAL strategy, restore drill, RPO/RTO |
| Reproducibility | NFR-MNT-1, NFR-MNT-2, §7.6 | `uv` lockfiles, pinned images, MLflow-backed reproducibility wiring |
| Secrets & security plumbing | NFR-SEC-2, NFR-SEC-3 (transport), partial NFR-SEC-1 wiring | `.env`/secret conventions, no secrets in git, TLS termination, least-priv DB roles |
| Testing / CI infra | NFR-TEST-1, NFR-TEST-2, NFR-TEST-3, §7.8 | CI pipeline: lint + type + test + data-validation + backtest gate |

**Acceptance criteria I am directly accountable for:** **AC-1** (automated end-to-end
pipeline runs — orchestration substrate), **AC-8** (full stack reproducibly via Docker
Compose from clean checkout), **AC-9** (RBAC wiring, logging, health monitoring,
automated backups operational), **AC-12** (data-validation + regression backtest pass
in CI). Partial enabling support for AC-7 (freshness/staleness plumbing) and AC-11
(audit-trail storage).

**Explicitly NOT mine** (I provide the seam, not the logic): SAR/water-mask logic
(FR-RS-*), ETL/feature logic (FR-DE-*), rating curve & ground-truthing (FR-GT-*),
ML models (FR-ML-*), API endpoint bodies (FR-API-*), UI components (FR-UI-*),
the frozen ABT/Observation column schema (`docs/contracts/observation-and-abt.md`,
ADR-0003 — owned by the data/ML contract team; I only host and version it).

---

## 2. Upstream dependencies (what I need from others before I can finish)

| Dep | From | Needed for | Fallback if late |
| --- | --- | --- | --- |
| Frozen ABT + Observation column schema (ADR-0003, `docs/contracts/observation-and-abt.md`) | Data/ML contract team | CI data-validation gate (`pandera`/GE suites reference it); DB schema in `core/` & `db/` | Stub schema + placeholder validation suite; gate runs but is permissive until frozen |
| SQLAlchemy models + Pydantic schemas in `core/` | Core/data team | `db/` Alembic autogen; API image build; pipeline worker imports | Empty `core` package that imports cleanly; compose still builds |
| GEE service-account JSON (non-commercial) | Project owner (credential) | `gee-auth` smoke test in CI/compose | Mock data-access backend (`fixtures`) keeps CI green without real creds |
| Reservoir AOI / catchment / rating-curve config files (FR-RS-1, FR-DE-7, ADR-0004) | RS + DE teams | Volume mounts + config loader paths | Sample config for the 3 pilot reservoirs |
| Backtest entrypoint (one-time walk-forward, FR-ML-6, NFR-TEST-3) | ML team | CI **backtest gate** (AC-12) needs an invocable, deterministic command | Marker-skipped placeholder test; gate wired but no-op until ML delivers |

These are tracked as blockers on the relevant tasks below (see `deps:` fields).

---

## 3. Downstream consumers (who builds on what I expose)

- **Remote-sensing team** → consumes `core` config loader, the `DataAccessBackend`
  abstraction, the Prefect flow-registration convention, structured-logging helper,
  and the pipeline-worker image.
- **Data-engineering team** → same worker image, `pandera`/GE validation hook in CI,
  PostGIS connection conventions, idempotent-upsert DB role.
- **ML team** → MLflow tracking URI + artifact store conventions, the backtest CI
  gate contract, model-version stamping helper.
- **API team** → `api` image, health-endpoint convention, DB read role, env-var
  contract, OpenAPI served behind the reverse proxy, audit-trail table location.
- **Web team** → `web` image + Vite build/runtime env convention, reverse-proxy
  routing (`/api`, `/mlflow`, `/prefect`), staleness flag surfaced by API.
- **All teams** → `uv` workspace root, `docker compose up` single-command bring-up,
  `.env.example` contract, CI gate definitions, the `make`/`task` developer commands.

---

## 4. Directory / module structure I establish

I scaffold the repository skeleton and the infra-owned files. Other teams fill in
their packages; I guarantee the workspace, build, and wiring.

```
reservoir_analytics/
├── pyproject.toml                  # uv workspace root (tool.uv.workspace)
├── uv.lock                         # single resolved lockfile (committed)
├── .python-version                 # pinned (3.12)
├── .env.example                    # canonical env contract (committed, no secrets)
├── .dockerignore  .gitignore  .editorconfig  .pre-commit-config.yaml
├── Taskfile.yml                    # task runner (up/down/test/lint/migrate/backup…)
├── README.md
│
├── core/                           # [core team] shared config + SQLAlchemy + Pydantic
│   ├── pyproject.toml
│   └── src/core/{config,models,schemas,logging,provenance}/   # I seed config+logging
│
├── db/                             # [core team] Alembic migrations
│   ├── pyproject.toml
│   ├── alembic.ini
│   └── migrations/{env.py, versions/}   # I seed env.py wiring + PostGIS bootstrap
│
├── pipelines/
│   ├── _common/                    # I seed: DataAccessBackend ABC, retry/backoff, run-context
│   │   └── src/pipelines_common/{dataaccess,retry,runlog}.py
│   ├── remote_sensing/             # [RS team]
│   ├── data_engineering/           # [DE team]
│   └── ml/                         # [ML team]   (each its own pyproject.toml workspace member)
│
├── orchestration/                  # Prefect 2 flows + deployments (I seed structure)
│   ├── pyproject.toml
│   └── src/orchestration/{flows,deployments,schedules}.py
│
├── api/                            # [API team] FastAPI app  (I seed image + health + settings)
│   ├── pyproject.toml
│   └── src/api/{main.py, health.py, settings.py}
│
├── web/                            # [web team] React + Vite + TS  (I seed Dockerfile + nginx + env)
│   ├── package.json  vite.config.ts  tsconfig.json
│   └── Dockerfile  nginx.conf
│
├── infra/
│   ├── docker/
│   │   ├── python.Dockerfile       # shared multi-stage base for api + workers + orchestration
│   │   ├── api.Dockerfile  worker.Dockerfile  orchestration.Dockerfile
│   │   ├── mlflow.Dockerfile  postgres/   (PostGIS init scripts + roles)
│   │   └── proxy/  (Caddy/nginx reverse-proxy + TLS config)
│   ├── compose/
│   │   ├── docker-compose.yml          # base
│   │   ├── docker-compose.override.yml # dev (hot reload, bind mounts)
│   │   └── docker-compose.prod.yml     # prod (TLS, restart policies, resource limits)
│   ├── scripts/  (backup.sh, restore.sh, wait-for-it, gee-auth-check.py)
│   └── ci/  (reusable CI step fragments if needed)
│
├── tests/                          # cross-cutting integration + e2e (unit tests live per package)
│   ├── integration/  e2e/  fixtures/
│   └── conftest.py
│
├── docs/
│   ├── plans/01-infrastructure-platform.md   ← this file
│   ├── adr/  contracts/
│   └── runbooks/  (backup-restore, incident, on-call — I author)
│
└── .github/workflows/
    ├── ci.yml                      # lint + type + test + data-validation + backtest gate
    └── images.yml                 # build/push images on tag (GHCR)
```

**Rationale for `pipelines/_common`:** the `DataAccessBackend` abstraction, retry/backoff,
and run-logging are shared across all three pipelines and must not live in any single
pipeline package (avoids circular deps and lets RS/DE/ML import one stable surface).

---

## 5. Detailed task breakdown

Tasks are small, sequenced, and each has an effort estimate (ideal engineering days),
explicit dependencies, and an acceptance check. `T-01..` ordering reflects the critical
path; parallelizable tasks note it.

### Phase A — Workspace & reproducibility foundation

**T-01 — Initialise `uv` workspace + repo skeleton** · 0.5d · deps: none
Create root `pyproject.toml` with `[tool.uv.workspace] members = ["core","db","pipelines/*","orchestration","api"]`, `.python-version` (3.12), per-member stub `pyproject.toml` files that import cleanly, `.gitignore`/`.dockerignore`/`.editorconfig`, and the directory tree in §4.
*Accept:* `uv sync` resolves and writes a single `uv.lock`; `uv run python -c "import core"` succeeds.

**T-02 — Pin toolchain + pre-commit** · 0.5d · deps: T-01
Add `ruff` (lint+format), `mypy`, `pytest`, `pre-commit` config. Configure ruff/mypy at root applying to all members.
*Accept:* `uv run ruff check .`, `uv run mypy .`, and `pre-commit run --all-files` all execute (may report findings, must not error on config).

**T-03 — Seed `core` config + structured logging + run-context** · 1d · deps: T-01
Seed `core.config` (pydantic-settings, reads env contract), `core.logging` (JSON structured logging via `structlog`, correlation/run-id binding), and a `RunContext` (run_id, reservoir_id, flow, started_at) used by all pipelines and the audit trail. *Coordinate with core team so models/schemas land in the same package.*
*Accept:* importing `core.config.settings` reads `.env`; `core.logging.get_logger()` emits one JSON line with run-id; unit test asserts JSON shape.

**T-04 — Taskfile developer commands** · 0.5d · deps: T-01
`task up/down/logs/test/lint/typecheck/migrate/backup/restore/seed/gee-check`. Single entry surface for humans and CI.
*Accept:* `task --list` shows all; `task lint` and `task typecheck` run.

### Phase B — Container topology

**T-05 — Shared Python base image (multi-stage, uv)** · 1d · deps: T-01
`infra/docker/python.Dockerfile`: builder stage runs `uv sync --frozen --no-dev` into a venv; runtime stage is slim, non-root, copies venv. Buildkit cache mounts for `uv`. Workers/api/orchestration derive from this.
*Accept:* image builds from clean checkout; `docker run … python -c "import core"` works; image is non-root (`whoami` ≠ root).

**T-06 — Postgres + PostGIS service** · 0.5d · deps: T-01
`postgis/postgis:16-3.4` (or build from `infra/docker/postgres`) with init scripts: `CREATE EXTENSION postgis;`, app DB, and **three least-privilege roles** — `app_rw` (API/pipelines write), `app_ro` (API read paths / web-serving), `mlflow` (MLflow backend store). Named volume for data.
*Accept:* `task up` brings Postgres healthy; `SELECT postgis_version();` returns; the three roles exist with scoped grants.

**T-07 — MLflow tracking server** · 0.5d · deps: T-06
MLflow server with Postgres backend store (`mlflow` role) + filesystem/`minio`-optional artifact store on a named volume. Open-source, self-hosted.
*Accept:* MLflow UI reachable behind proxy at `/mlflow`; a smoke `mlflow.log_metric` from a worker container persists to Postgres.

**T-08 — Prefect 2 server + agent/worker** · 1d · deps: T-05, T-06
Self-hosted Prefect 2 (`prefecthq/prefect:2-*`) Orion server using Postgres for its metadata DB; a Prefect **worker** in a pool (`reservoir-pool`). Orchestration image derives from the base image so flows can import all pipeline packages.
*Accept:* Prefect UI reachable at `/prefect`; a trivial registered flow runs to `Completed` via the worker; flow run history visible.

**T-09 — API + Web service images + reverse proxy + TLS** · 1d · deps: T-05
`api.Dockerfile` (uvicorn, non-root, exposes `/health`), `web/Dockerfile` (Vite build → static, served by nginx), and a **Caddy** reverse proxy terminating TLS and routing `/` → web, `/api` → api, `/mlflow`, `/prefect`. Caddy auto-provisions local/self-signed certs in dev, real certs in prod. (Caddy chosen for zero-config TLS; NFR-SEC-3.)
*Accept:* `https://localhost` serves web; `https://localhost/api/health` returns 200; `/mlflow` and `/prefect` proxy through.

**T-10 — Compose: base + dev override + prod** · 1d · deps: T-06..T-09
`docker-compose.yml` defines services `postgres, mlflow, prefect-server, prefect-worker, api, web, proxy` plus profile-gated `pipeline-worker` (scalable). `override` adds bind-mounts + hot reload; `prod` adds `restart: unless-stopped`, resource limits, healthchecks, no source mounts. **Service names are a published contract (§6).**
*Accept (AC-8):* from a clean checkout, `cp .env.example .env && task up` brings the whole stack healthy with one command; `docker compose ps` shows all healthy.

### Phase C — Config, secrets, data-access abstraction

**T-11 — Env/secrets contract + `.env.example`** · 0.5d · deps: T-03
Canonical, namespaced env vars (§6). `.env` git-ignored; `.env.example` committed with safe placeholders. GEE service-account JSON mounted as a file via `GEE_SA_KEY_FILE` path (never inlined). Document a clean migration path to Docker secrets / Vault for prod.
*Accept (NFR-SEC-2):* `git check-ignore .env` succeeds; CI secret-scan (gitleaks) passes; no service reads a secret outside the documented vars.

**T-12 — `DataAccessBackend` abstraction (swappable GEE layer)** · 1.5d · deps: T-03
Define the thin ABC in `pipelines/_common` (signature in §6) with two implementations registered by factory: `GEEBackend` (geemap/xee, the v1 default) and `FixtureBackend` (canned `xarray`/GeoJSON for tests/CI without credentials). Future `openEO`/`PlanetaryComputer` backends slot in without touching callers (§4.4 swappability).
*Accept (§4.4):* `get_backend("gee")` and `get_backend("fixture")` both satisfy the ABC; RS/DE pipelines import only the ABC; a contract test runs every backend through the same interface assertions.

**T-13 — GEE auth + smoke check** · 0.5d · deps: T-12
`infra/scripts/gee-auth-check.py` initialises EE from the mounted service-account key and runs a 1-pixel reduce. Wired into `task gee-check` and an *opt-in* CI job (skipped when no creds).
*Accept:* with creds present, returns a value and exit 0; without creds, exits with a clear, non-cryptic message; CI green either way.

### Phase D — Reliability, observability, degradation

**T-14 — Retry/backoff + idempotency helpers** · 1d · deps: T-03
`pipelines_common.retry` (tenacity-based exponential backoff + jitter, classified transient vs permanent), and an idempotent-upsert helper keyed by `(reservoir_id, acquisition_date|date)` for pipeline writes.
*Accept (NFR-REL-1):* unit test forces 2 transient failures then success; permanent error is not retried; re-running an upsert twice yields one row.

**T-15 — Run-history + audit-trail storage** · 1d · deps: T-06, T-03
Tables (via `db/` migration, coordinated with core team): `pipeline_run` (flow, reservoir, status, started/ended, rows_in/out, error) and `audit_log` (immutable: what predicted/alerted, when, on which data + model version — NFR-REL-5, supports AC-11). Append-only; admin-queryable.
*Accept (NFR-REL-2, NFR-REL-5):* a flow run writes a `pipeline_run` row queryable by admin; `audit_log` insert-only (no update/delete grant for app role).

**T-16 — Health endpoints + healthchecks** · 0.5d · deps: T-09, T-06
Seed `/health` (liveness) and `/health/ready` (readiness: DB reachable, MLflow reachable, last-acquisition freshness) in the API; Compose `healthcheck` for every service.
*Accept (NFR-REL-2, NFR-REL-3):* `/health/ready` returns dependency status JSON; `docker compose ps` reports health for all services.

**T-17 — Graceful degradation / staleness plumbing** · 1d · deps: T-15, T-16
Infra surface for NFR-REL-6 / AC-7: a `data_freshness` view/helper computing per-reservoir `last_acquisition_date`, `age_days`, and a `stale` boolean against a configurable threshold; exposed via API readiness + a field the API returns so the system **keeps serving last-known forecast-based risk and flags staleness** instead of going silent. (Logic of *what* to serve is API/ML; I provide the freshness signal + the convention.)
*Accept (NFR-REL-6):* with no fresh imagery (simulated), the freshness helper reports `stale=true` and `age_days`; nothing errors; a `stale-data` signal is available to API/alerts.

**T-18 — Centralised log aggregation (dev-grade, open-source)** · 0.5d · deps: T-03
JSON logs to stdout from all services; optional Compose profile adding Loki + Grafana (or Dozzle for a lightweight default) for searchable logs/dashboards. Stays fully open-source.
*Accept (NFR-REL-2):* structured logs from ≥3 services are searchable in one place when the `observability` profile is up.

### Phase E — Backups

**T-19 — Automated DB backups + restore drill** · 1d · deps: T-06
`infra/scripts/backup.sh` (`pg_dump` custom format, nightly via a small `cron`/`ofelia` sidecar container, retained N days, timestamped) + `restore.sh`. Document **RPO ≤ 24h, RTO ≤ 1h** (NFR-REL-4). Optional WAL archiving noted as a prod upgrade for tighter RPO.
*Accept (NFR-REL-4, AC-9):* `task backup` produces a dated dump; `task restore` rebuilds into a scratch DB and row counts match; runbook documents RPO/RTO.

### Phase F — CI / testing infrastructure

**T-20 — CI: lint + type + unit/integration tests** · 1d · deps: T-02, T-10
`.github/workflows/ci.yml`: `uv sync --frozen`; jobs for `ruff`, `mypy`, `pytest` (unit per-package + integration against an ephemeral Postgres+PostGIS service container). Cache `uv`.
*Accept (NFR-TEST-2):* PR triggers all jobs; a failing lint/type/test fails the PR; lockfile drift (`uv lock --check`) fails CI.

**T-21 — CI: automated data-validation gate** · 1d · deps: T-20, dep: ABT/Observation schema (ADR-0003)
A CI job runs the `pandera`/Great-Expectations suites (authored against the frozen ABT/Observation contract) over fixture data: schema, ranges (fill % 0–110, area ≥ 0, level ≤ FRL+tol), nulls, temporal continuity, cross-field consistency. Failing data is reported as a gate, not silently passed.
*Accept (NFR-TEST-1, AC-12):* a deliberately-malformed fixture fails the job; clean fixture passes.

**T-22 — CI: regression backtest gate** · 1d · deps: T-20, dep: ML backtest entrypoint (FR-ML-6)
A CI job invokes the deterministic, fixture-scaled end-to-end backtest against a known historical near-FRL episode (NFR-TEST-3) and asserts the published metric thresholds (estimation MAE, forecast-beats-baseline). Until ML delivers the entrypoint, this is a marker-skipped placeholder so the gate is wired (AC-12).
*Accept (NFR-TEST-3, AC-12):* the backtest job runs in CI; below-threshold metrics fail the build; results artifact uploaded.

**T-23 — Image build/publish workflow** · 0.5d · deps: T-05, T-09
`.github/workflows/images.yml`: on tag, build all images via Buildkit and push to GHCR (free for the repo). Tags pinned by git SHA + semver.
*Accept (NFR-MNT-1):* a tag produces pinned, pullable images; digests recorded.

### Phase G — Documentation & handoff

**T-24 — Runbooks + ADR for infra decisions** · 0.5d · deps: T-19, T-10
Runbooks: backup/restore, incident, local bring-up; an ADR recording orchestrator=Prefect 2, proxy=Caddy, and the data-access swappability stance (cross-refs §4.4 / ADR licensing note).
*Accept:* runbooks executable by someone who didn't write them; ADR merged.

**Total critical-path estimate:** ~18–20 ideal-engineering-days; Phases B/C/D parallelize
across 2 engineers to ~10–12 calendar days.

---

## 6. Interfaces / contracts I expose to other teams

These are stable surfaces. Other teams should align to them and flag changes via ADR.

### 6.1 Compose service names (DNS within the network)

| Service | Name | Port(s) | Notes |
| --- | --- | --- | --- |
| Database | `postgres` | 5432 | PostGIS; roles `app_rw`, `app_ro`, `mlflow` |
| ML lifecycle | `mlflow` | 5000 | tracking URI `http://mlflow:5000` |
| Orchestrator API/UI | `prefect-server` | 4200 | `PREFECT_API_URL=http://prefect-server:4200/api` |
| Orchestrator worker | `prefect-worker` | — | pool `reservoir-pool` |
| Backend API | `api` | 8000 | `/health`, `/health/ready`, `/docs` |
| Frontend | `web` | 80 | static build |
| Pipeline workers | `pipeline-worker` | — | scalable: `docker compose up --scale pipeline-worker=N` (NFR-SCALE-2) |
| Reverse proxy / TLS | `proxy` | 80/443 | routes `/`,`/api`,`/mlflow`,`/prefect` |

### 6.2 Environment-variable convention

Namespaced `UPPER_SNAKE`. Canonical set in `.env.example`. Secrets are file-mounted
where possible (NFR-SEC-2). Representative contract:

```
# --- Database ---
POSTGRES_HOST=postgres   POSTGRES_PORT=5432   POSTGRES_DB=reservoir
DATABASE_URL_RW=postgresql+psycopg://app_rw:***@postgres:5432/reservoir
DATABASE_URL_RO=postgresql+psycopg://app_ro:***@postgres:5432/reservoir
# --- MLflow ---
MLFLOW_TRACKING_URI=http://mlflow:5000
MLFLOW_ARTIFACT_ROOT=/artifacts
# --- Prefect ---
PREFECT_API_URL=http://prefect-server:4200/api
# --- GEE (file-mounted, never inlined) ---
GEE_SA_KEY_FILE=/run/secrets/gee_sa.json
GEE_PROJECT=<ee-project>
DATA_ACCESS_BACKEND=gee            # gee | fixture | (future: openeo, planetary)
# --- App / observability ---
APP_ENV=dev                        # dev | prod
LOG_LEVEL=INFO   LOG_FORMAT=json
DATA_STALENESS_THRESHOLD_DAYS=14   # drives NFR-REL-6 staleness flag
# --- Auth (wiring; RBAC logic owned by API team) ---
JWT_SECRET_FILE=/run/secrets/jwt_secret
```

Rule: a service may only read vars in this contract; new vars are added here first.

### 6.3 CI gates (a PR must pass all)

1. **lint** (`ruff check` + format check) · 2. **type** (`mypy`) · 3. **lockfile**
(`uv lock --check`) · 4. **unit + integration tests** (`pytest`, ephemeral PostGIS)
· 5. **data-validation gate** (`pandera`/GE over fixtures — NFR-TEST-1) · 6.
**regression backtest gate** (NFR-TEST-3) · 7. **secret scan** (gitleaks). Gates 5 & 6
are the AC-12 gates.

### 6.4 Data-access abstraction signature (the swappable GEE seam, §4.4)

```python
# pipelines/_common/src/pipelines_common/dataaccess.py
from abc import ABC, abstractmethod
from datetime import date
import xarray as xr

class DataAccessBackend(ABC):
    """Thin, swappable satellite/geodata access boundary.
    v1 impl: GEE (geemap/xee). Designed so an openEO / Planetary Computer
    backend can replace it without changing any pipeline caller (§4.4)."""

    @abstractmethod
    def get_s1_grd(self, aoi: dict, start: date, end: date,
                   orbit: str, pass_dir: str) -> xr.Dataset: ...
    """Sentinel-1 GRD scenes over an AOI GeoJSON, fixed orbit/pass (FR-RS-1)."""

    @abstractmethod
    def get_dem(self, aoi: dict, asset: str = "COPERNICUS/DEM/GLO30") -> xr.Dataset: ...

    @abstractmethod
    def get_collection(self, asset_id: str, region: dict,
                       start: date, end: date, bands: list[str]) -> xr.Dataset: ...
    """Generic catchment-forcing pull (ERA5-Land, IMERG, GFS, MODIS, …) → xarray (FR-DE-8..10)."""

    @abstractmethod
    def list_scenes(self, asset_id: str, aoi: dict,
                    start: date, end: date) -> list[dict]: ...
    """Scene metadata for nearest-match + freshness (FR-GT-1, NFR-TIME-1)."""

def get_backend(name: str | None = None) -> DataAccessBackend: ...
    # factory; reads DATA_ACCESS_BACKEND when name is None
```

### 6.5 Other conventions

- **Health:** every long-running service exposes `/health` (liveness) and, where it has
  dependencies, `/health/ready` (readiness JSON). Compose healthchecks required.
- **Logging:** JSON to stdout via `core.logging`; every pipeline run binds `run_id`,
  `reservoir_id`, `flow`. No `print`.
- **Idempotency:** all pipeline writes use the upsert helper keyed by
  `(reservoir_id, acquisition_date|date)` (§4.3, NFR-REL-1).
- **Run/audit:** pipelines write a `pipeline_run` row; predictions/alerts write
  `audit_log` (NFR-REL-5).
- **Flow registration:** Prefect flows live in `orchestration/`, deployed to
  `reservoir-pool`; RS-success triggers DE, DE-success triggers ML (§4.3, AC-1).

---

## 7. Library / tool choices (rationale & versions)

Versions are floors; exact pins land in `uv.lock` / image tags. All open-source/free (§4.4).

| Concern | Choice | Version (floor) | Rationale |
| --- | --- | --- | --- |
| Python | CPython | 3.12.x | Modern typing, broad geospatial wheel support; pinned via `.python-version` |
| Env/packaging | **uv** | ≥ 0.5 | Mandated (§4.2); fast, reproducible, single workspace lockfile (NFR-MNT-1) |
| Lint/format | ruff | ≥ 0.6 | One fast tool for lint+format; replaces flake8/black/isort |
| Types | mypy | ≥ 1.11 | Static typing gate in CI (NFR-TEST-2) |
| Tests | pytest (+pytest-cov) | ≥ 8 | De-facto standard; integration via service containers |
| Settings | pydantic-settings | ≥ 2 | Typed env contract; pairs with the Pydantic schemas in `core` |
| Structured logging | structlog | ≥ 24 | JSON logs + run-id binding (NFR-REL-2) |
| Retry/backoff | tenacity | ≥ 9 | Exponential backoff + jitter, transient classification (NFR-REL-1) |
| Data validation | pandera (+ optional Great Expectations) | pandera ≥ 0.20 | Lightweight, code-first schema/range checks in CI + per-run (NFR-TEST-1); GE optional for richer suites |
| Orchestrator | **Prefect 2** (self-hosted OSS) | 2.x | Shared decision; OSS, container-friendly, native retries/scheduling/observability (§4.3) |
| ML lifecycle | MLflow | ≥ 2.14 | Mandated (§4.2); Postgres backend + artifact store (NFR-MNT-2) |
| Database | PostgreSQL + PostGIS | PG 16 / PostGIS 3.4 | Mandated (§4.2); geometry + time-series + app data |
| DB driver / ORM | psycopg 3 + SQLAlchemy 2 | sa ≥ 2 / psycopg ≥ 3.2 | Async-capable, typed; pairs with GeoAlchemy2 for PostGIS |
| Migrations | Alembic | ≥ 1.13 | Versioned schema in `db/`; PostGIS extension bootstrap |
| API server | FastAPI + uvicorn | fastapi ≥ 0.111 | Mandated (§4.2); typed, OpenAPI built-in |
| Frontend | React + Vite + TypeScript + Leaflet | React 18 / Vite 5 | Mandated (§4.2) |
| Reverse proxy / TLS | **Caddy** | 2.x | Zero-config automatic TLS (NFR-SEC-3); simpler than nginx for this |
| Containers | Docker + Compose v2 | Engine ≥ 26 | Mandated (§4.2); Buildkit multi-stage |
| Backup scheduler | ofelia (or cron sidecar) | latest | Tiny OSS cron-in-Docker for nightly `pg_dump` (NFR-REL-4) |
| Secret scan | gitleaks | ≥ 8 | CI guard against committed secrets (NFR-SEC-2) |
| Log aggregation (opt.) | Loki + Grafana, or Dozzle | latest | OSS searchable logs (NFR-REL-2); profile-gated to keep base light |
| CI | GitHub Actions | — | Free for the repo; GHCR for images |
| Task runner | go-task (Taskfile) | 3.x | Cross-platform single command surface (works on the Windows dev host) |

---

## 8. Testing / validation strategy

- **Unit (per package):** config loader, logging shape, retry classification, upsert
  idempotency, `DataAccessBackend` factory + `FixtureBackend` contract.
- **Backend contract tests:** run `GEEBackend` (creds-gated, opt-in) and `FixtureBackend`
  through identical interface assertions so the swappable seam (§4.4) can't drift.
- **Integration (CI, ephemeral PostGIS):** Alembic migrations apply cleanly; PostGIS
  extension present; the three roles have correct grants; `pipeline_run`/`audit_log`
  write+query; idempotent upsert end-to-end.
- **Data-validation gate (NFR-TEST-1, AC-12):** `pandera`/GE suites over good *and*
  deliberately-malformed fixtures; malformed must fail.
- **Regression backtest gate (NFR-TEST-3, AC-12):** deterministic fixture-scaled
  end-to-end backtest on a known near-FRL episode; asserts metric thresholds.
- **Compose smoke (AC-8):** CI job does `cp .env.example .env && docker compose up -d`
  with the `fixture` backend, polls every `/health/ready`, then tears down — proving
  clean-checkout reproducibility without real GEE creds.
- **Backup/restore drill (NFR-REL-4, AC-9):** scripted dump → restore into scratch DB →
  row-count parity, exercised in a scheduled CI job.
- **Security checks:** gitleaks in CI; verify `.env` is git-ignored; confirm services
  read only contract vars.

---

## 9. Risks & open decisions

| Risk / decision | Impact | Disposition |
| --- | --- | --- |
| **GEE non-commercial licensing** (§4.4) | Commercialisation blocked on this backend | Mitigated by `DataAccessBackend` swappability (T-12); documented in ADR; no other infra depends on GEE |
| Backtest gate depends on ML entrypoint (FR-ML-6) | AC-12 not fully provable until ML lands | Gate wired now as marker-skip placeholder; flips to enforcing on delivery |
| Data-validation gate depends on frozen ABT/Observation schema (ADR-0003) | Strictness limited until schema frozen | Permissive stub suite now; tighten on freeze |
| Windows dev host (current cwd is `win32`) | Shell-script backups, line endings, bind-mount perf | Use `go-task` + POSIX scripts run *inside* containers; `.editorconfig`/`.gitattributes` enforce LF; document WSL2/Docker Desktop |
| Single-host Compose vs orchestration at scale | NFR-SCALE-2 satisfied via `--scale` only on one host | Compose meets v1 fleet (3 reservoirs); note Kubernetes/Swarm as a v2 path; keep services stateless to ease migration |
| Secrets: `.env` vs Docker secrets/Vault | Prod hardening | v1 uses file-mounted secrets + git-ignored `.env`; documented upgrade path to Docker secrets / Vault |
| MLflow artifact store: filesystem vs MinIO | Portability of artifacts | Default filesystem volume; MinIO is an optional profile if object storage is wanted |
| **Open decision — proxy/TLS: Caddy vs nginx vs Traefik** | Affects web/api routing config other teams reference | Proposing **Caddy** (auto-TLS, simplest); confirm before web team hardcodes asset base paths |
| **Open decision — log aggregation default** (Dozzle vs Loki/Grafana) | Ops experience | Proposing Dozzle as the light default, Loki/Grafana behind a profile |
| **Open decision — staleness threshold default** (`DATA_STALENESS_THRESHOLD_DAYS`) | Drives NFR-REL-6 behavior shared with API/ML | Proposing 14d (upper Sentinel-1 revisit); needs sign-off from ML/API as it gates "stale" UI state |

---

## 10. Mapping to acceptance criteria

| AC / NFR | Where satisfied |
| --- | --- |
| **AC-1** (pipelines run end-to-end automatically) | T-08 (Prefect server/worker), §6.5 flow-trigger convention, T-14 idempotency/retry — *substrate*; pipeline logic owned by RS/DE/ML |
| **AC-8** (full stack reproducibly via Docker Compose from clean checkout) | T-01 uv workspace, T-05 base image, T-10 compose, §8 compose-smoke CI job |
| **AC-9** (RBAC, logging, health, automated backups operational) | RBAC wiring T-11/§6.2 (logic = API team) · logging T-03/T-18 · health T-16 · backups T-19 |
| **AC-12** (data-validation + regression backtest pass in CI) | T-21 (data-validation gate), T-22 (backtest gate), §6.3 |
| AC-7 (data freshness within SLA, staleness shown) | T-17 staleness plumbing + T-16 readiness freshness (UI/ML consume) |
| AC-11 (in-app alert persisted + audit trail) | T-15 `audit_log` storage (alert logic = API/ML) |
| NFR-REL-1 | T-14 retry/backoff/idempotency |
| NFR-REL-2 | T-03/T-18 structured logging, T-15 run-history, T-16 health |
| NFR-REL-3 | T-09 proxy + T-16 healthchecks + Compose restart policies |
| NFR-REL-4 | T-19 backups + restore drill (RPO ≤ 24h / RTO ≤ 1h) |
| NFR-REL-5 | T-15 immutable `audit_log` |
| NFR-REL-6 | T-17 graceful-degradation / staleness plumbing |
| NFR-SCALE-1/2 | T-10 scalable `pipeline-worker`, stateless API, config-driven fleet |
| NFR-SEC-2/3 | T-11 secrets contract + gitleaks, T-09 TLS proxy + least-priv DB roles (T-06) |
| NFR-MNT-1/2 | T-01 uv lockfile + T-23 pinned images, T-07 MLflow reproducibility wiring |
| NFR-TEST-1/2/3 | T-20 (lint/type/test), T-21 (data-validation), T-22 (backtest) |
```

*End of plan.*
