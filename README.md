# Reservoir Monitoring & Analytics Platform

Disaster-management platform that monitors reservoirs from Sentinel-1 SAR + DEM and
predicts the likelihood of a water release, to give downstream communities early flood
warning. See [`requirements.md`](requirements.md) for the full spec, [`CONTEXT.md`](CONTEXT.md)
for the domain glossary, [`docs/adr/`](docs/adr) for decisions, and
[`docs/plans/`](docs/plans) for the implementation plans.

## Architecture (the spine)

```
SAR → water extraction (ADR-0007) → area → blended rating curve / estimation bridge
   (ADR-0004) → storage → pooled Δ-fill forecaster (ADR-0006) → forecast
   → release-risk layer (ADR-0001)
```

Closed loop (ADR-0005): bulletins (2015–2026) are a historical bootstrap; production runs
on SAR + DEM + forcing with no live ground truth. The frozen inter-pipeline contract is
[`docs/contracts/observation-and-abt.md`](docs/contracts/observation-and-abt.md).

## Layout

`core/` shared config + SQLAlchemy models + Pydantic schemas · `db/` Alembic migrations ·
`pipelines/` remote-sensing / data-engineering / ml (+ `_common` `DataAccessBackend`) ·
`orchestration/` Prefect flows · `api/` FastAPI · `web/` dashboard (fullscreen SAR-timeline
map console; smoke script in [`docs/runbooks/dashboard-smoke.md`](docs/runbooks/dashboard-smoke.md)) ·
`infra/` Docker topology.

## Quickstart (dev)

Requires Docker, [`uv`](https://docs.astral.sh/uv/), and (optionally) [`go-task`](https://taskfile.dev).

```bash
cp .env.example .env            # never commit .env; the GEE key (geeservice.json) is git-ignored
uv sync                         # resolve the workspace
task up                         # bring up the full stack (or: docker compose -f infra/compose/docker-compose.yml up -d)
task migrate                    # apply DB migrations
task ci                         # lint + typecheck + test locally
```

If a local PostgreSQL already owns port 5432, publish the container elsewhere:
`POSTGRES_HOST_PORT=55432 task up-db` and point host tooling at `localhost:55432`.

## Status

Phases 0–9 machinery is built end-to-end (DB → pipelines → API → dashboard); see
[`todos.md`](todos.md) for the phased checklist. Validation so far is **synthetic**
(fixture backend) — the GEE-dependent science pass is still pending, so accuracy figures
are machinery checks, not real skill. An active remediation effort from the 2026-07-03
critical review is underway: [`remediation-todos.md`](remediation-todos.md).

## Secrets

`geeservice.json` is a **live GEE service-account key** — it is git-ignored, but it should
live *outside* the repo entirely and be file-mounted per the `/run/secrets/gee_sa.json`
convention in [`.env.example`](.env.example) (`GEE_SA_KEY_FILE`). Never commit it or bake
it into images.
