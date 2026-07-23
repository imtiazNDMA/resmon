@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ============================================================
REM  Reservoir Monitoring & Analytics - one-command local start
REM  Brings up Postgres (Docker), migrates + populates the DB,
REM  then starts the API and the web dashboard, and opens it.
REM
REM  Requirements: Docker Desktop running, `uv`, and Node.js.
REM  Postgres is published on host port 55432 to avoid clashing
REM  with any local PostgreSQL on 5432.
REM ============================================================

set POSTGRES_HOST_PORT=55432
set DATABASE_URL_RW=postgresql+psycopg://app_rw:app_rw@localhost:55432/reservoir
set DATABASE_URL_RO=postgresql+psycopg://app_ro:app_ro@localhost:55432/reservoir
set DATA_ACCESS_BACKEND=fixture
set LOKY_MAX_CPU_COUNT=2
if exist "geeservice.json" set GEE_SA_KEY_FILE=geeservice.json
set COMPOSE=docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.override.yml

echo ============================================================
echo  Reservoir Monitoring ^& Analytics - starting up
echo ============================================================

echo [1/6] Starting PostgreSQL + PostGIS (Docker)...
%COMPOSE% up -d postgres
if errorlevel 1 ( echo   ERROR: could not start Postgres. Is Docker Desktop running? & pause & exit /b 1 )

echo [2/6] Waiting for the database to accept connections...
:waitdb
%COMPOSE% exec -T postgres pg_isready -U postgres -d reservoir >nul 2>&1
if errorlevel 1 ( timeout /t 2 >nul & goto waitdb )

echo        Ensuring local database privileges are current...
%COMPOSE% exec -T postgres psql -U postgres -d reservoir -f /docker-entrypoint-initdb.d/02-dev-repair-privileges.sql >nul
if errorlevel 1 ( echo   ERROR: could not repair local database privileges. & pause & exit /b 1 )

echo [3/6] Preparing Python environment (uv sync)...
call uv sync
if errorlevel 1 ( echo   ERROR: uv sync failed. Is uv installed? & pause & exit /b 1 )

echo [4/6] Applying database migrations...
call uv run alembic -c db/alembic.ini upgrade head
if errorlevel 1 ( echo   ERROR: migrations failed. & pause & exit /b 1 )

echo [5/9] Populating data with the full pipeline (one-time, ~30s)...
call uv run python scripts/bootstrap.py
if errorlevel 1 ( echo   ERROR: bootstrap failed. & pause & exit /b 1 )

echo [6/9] Loading historical Sentinel-1 backfill for the time slider...
call uv run python scripts/load_backfill.py
if errorlevel 1 ( echo   ERROR: backfill load failed. & pause & exit /b 1 )

echo [7/9] Fetching latest available REAL satellite overlays from Google Earth Engine (~1-2 min)...
echo        (AOI from JRC GSW, catchment from HydroBASINS, Sentinel-1 water extent)
call uv run python scripts/populate_geometry.py
if errorlevel 1 ( echo   NOTE: GEE geometry skipped - check geeservice.json / network. The app still runs with placeholder AOIs. )

echo [8/9] Refreshing current-level estimation from loaded imagery...
call uv run python scripts/refresh_estimation_after_imagery.py
if errorlevel 1 ( echo   ERROR: estimation refresh failed. & pause & exit /b 1 )

echo [9/9] Starting API (port 18001) and web dashboard (port 5173)...
start "Reservoir API" cmd /k uv run uvicorn api.main:app --host 0.0.0.0 --port 18001
if not exist "web\node_modules" (
  echo        Installing web dependencies ^(first run only, please wait^)...
  pushd web && call npm install && popd
)
start "Reservoir Web" cmd /k "cd web && npm run dev"

echo.
echo        Waiting for the dev server to come up...
timeout /t 12 >nul
start "" http://localhost:5173

echo.
echo ============================================================
echo  Dashboard : http://localhost:5173
echo  API + docs: http://localhost:18001/docs
echo  Database  : localhost:55432  (Docker; data persists)
echo.
echo  Two windows opened (API + Web) - close them to stop those.
echo  Stop Postgres:  %COMPOSE% down
echo ============================================================
echo.
pause
endlocal
