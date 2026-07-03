#!/bin/bash
# First-boot init for the reservoir database (runs once, as the superuser, against
# POSTGRES_DB). Enables PostGIS and creates the least-privilege roles (NFR-SEC-3).
#
# Role passwords come from the environment (D2) — no hardcoded credentials here.
# Dev defaults are injected by infra/compose/docker-compose.override.yml; prod must
# set APP_RW_PASSWORD / APP_RO_PASSWORD / MLFLOW_DB_PASSWORD / PREFECT_DB_PASSWORD.
# Passwords must not contain single quotes (they are spliced into SQL literals).
set -euo pipefail

: "${APP_RW_PASSWORD:?APP_RW_PASSWORD must be set (dev default comes from the compose dev override)}"
: "${APP_RO_PASSWORD:?APP_RO_PASSWORD must be set (dev default comes from the compose dev override)}"
: "${MLFLOW_DB_PASSWORD:?MLFLOW_DB_PASSWORD must be set (dev default comes from the compose dev override)}"
: "${PREFECT_DB_PASSWORD:?PREFECT_DB_PASSWORD must be set (dev default comes from the compose dev override)}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
	CREATE EXTENSION IF NOT EXISTS postgis;
	CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid() for later phases

	-- Application roles: app_rw writes (API pipelines, migrations own DDL),
	-- app_ro is the serving layer's read-only role.
	CREATE ROLE app_rw LOGIN PASSWORD '${APP_RW_PASSWORD}';
	CREATE ROLE app_ro LOGIN PASSWORD '${APP_RO_PASSWORD}';
	-- MLflow / Prefect get their own databases (D11) so their tables never
	-- pollute the app database (keeps 'alembic check' truthful).
	CREATE ROLE mlflow LOGIN PASSWORD '${MLFLOW_DB_PASSWORD}';
	CREATE ROLE prefect LOGIN PASSWORD '${PREFECT_DB_PASSWORD}';

	-- Bound the public query surface (D4): the read-only role can never hold a
	-- connection hostage with a pathological query.
	ALTER ROLE app_ro SET statement_timeout = '5s';

	-- Schema usage + sane default privileges. app_rw owns DDL via migrations.
	GRANT ALL ON SCHEMA public TO app_rw;
	GRANT USAGE ON SCHEMA public TO app_ro;

	ALTER DEFAULT PRIVILEGES FOR ROLE app_rw IN SCHEMA public
	    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw;
	ALTER DEFAULT PRIVILEGES FOR ROLE app_rw IN SCHEMA public
	    GRANT SELECT ON TABLES TO app_ro;
	ALTER DEFAULT PRIVILEGES FOR ROLE app_rw IN SCHEMA public
	    GRANT USAGE, SELECT ON SEQUENCES TO app_rw, app_ro;

	-- Dedicated service databases (D11).
	CREATE DATABASE mlflow_db OWNER mlflow;
	CREATE DATABASE prefect_db OWNER prefect;
EOSQL
