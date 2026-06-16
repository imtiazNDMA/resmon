# Runbook — Local bring-up

## One command (Windows)

```bat
start.bat
```

This: starts Postgres+PostGIS (Docker, host port **55432**), `uv sync`, applies
migrations, runs the full pipeline to populate data (fixture backend — no GEE needed),
then launches the API (`:18000`) and the web dashboard (`:5173`) and opens the browser.

- **Dashboard:** http://localhost:5173
- **API + OpenAPI docs:** http://localhost:18000/docs
- Re-running `start.bat` is safe (idempotent upserts).

## Manual / cross-platform

```bash
export POSTGRES_HOST_PORT=55432
export DATABASE_URL_RW=postgresql+psycopg://app_rw:app_rw@localhost:55432/reservoir
export DATABASE_URL_RO=postgresql+psycopg://app_ro:app_ro@localhost:55432/reservoir
export DATA_ACCESS_BACKEND=fixture

docker compose -f infra/compose/docker-compose.yml up -d postgres
uv run alembic -c db/alembic.ini upgrade head
uv run python scripts/bootstrap.py                       # populate (commits)
uv run uvicorn api.main:app --port 18000 &               # API
cd web && npm install && npm run dev                     # dashboard on :5173
```

## Notes

- **Why port 55432?** A local PostgreSQL on the default `5432` shadows the container;
  `POSTGRES_HOST_PORT` republishes it. Use `5432` if you have no local Postgres.
- **Synthetic data caveat.** The bootstrap uses the fixture data-access backend and
  synthetic SAR/forcing, so accuracy figures (AC-2 fill-% MAE, forecast skill) are
  *machinery checks*, not real accuracy — that needs live GEE credentials
  (`DATA_ACCESS_BACKEND=gee`, `GEE_SA_KEY_FILE`). Release-risk shows **Low** because the
  latest bulletin is a spring-recession state; the `stale` flag is **true** because the
  historical bulletins end in April 2026 (closed loop, ADR-0005).
- **Stop everything:** close the API/Web windows; `docker compose -f infra/compose/docker-compose.yml down`.
- **Tests:** `uv run pytest -q` (needs the DB up; uses the fixture backend).
