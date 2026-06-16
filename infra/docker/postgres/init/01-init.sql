-- First-boot init for the reservoir database (runs once as superuser on the
-- POSTGRES_DB). Enables PostGIS and creates the three least-privilege roles
-- (NFR-SEC-3). Dev passwords; rotate via secrets in prod.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid() for later phases

-- Application read-write role (API writes, pipelines write).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
        CREATE ROLE app_rw LOGIN PASSWORD 'app_rw';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_ro') THEN
        CREATE ROLE app_ro LOGIN PASSWORD 'app_ro';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mlflow') THEN
        CREATE ROLE mlflow LOGIN PASSWORD 'mlflow';
    END IF;
END
$$;

-- Schema usage + sane default privileges. app_rw owns DDL via migrations.
GRANT ALL ON SCHEMA public TO app_rw;
GRANT USAGE ON SCHEMA public TO app_ro;

ALTER DEFAULT PRIVILEGES FOR ROLE app_rw IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw;
ALTER DEFAULT PRIVILEGES FOR ROLE app_rw IN SCHEMA public
    GRANT SELECT ON TABLES TO app_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE app_rw IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_rw, app_ro;
