-- Idempotent repair for local dev volumes created before migrations ran as app_rw.
-- Extension-owned PostGIS objects are intentionally skipped.

GRANT ALL ON SCHEMA public TO app_rw;
GRANT USAGE ON SCHEMA public TO app_ro;

DO $$
DECLARE
    obj record;
    obj_type text;
BEGIN
    FOR obj IN
        SELECT c.oid, n.nspname, c.relname, c.relkind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
          AND NOT EXISTS (
              SELECT 1
              FROM pg_depend d
              WHERE d.objid = c.oid
                AND d.deptype = 'e'
          )
    LOOP
        obj_type := CASE obj.relkind
            WHEN 'S' THEN 'SEQUENCE'
            WHEN 'v' THEN 'VIEW'
            WHEN 'm' THEN 'MATERIALIZED VIEW'
            ELSE 'TABLE'
        END;

        EXECUTE format('ALTER %s %I.%I OWNER TO app_rw', obj_type, obj.nspname, obj.relname);
    END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_rw;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO app_ro;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_rw, app_ro;

ALTER DEFAULT PRIVILEGES FOR ROLE app_rw IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw;
ALTER DEFAULT PRIVILEGES FOR ROLE app_rw IN SCHEMA public
    GRANT SELECT ON TABLES TO app_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE app_rw IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_rw, app_ro;
