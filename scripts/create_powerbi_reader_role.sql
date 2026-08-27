-- Read-only Postgres role for Power BI (or any other external BI/reporting
-- tool) to connect with, instead of using the app's own `erp` credentials.
--
-- The `erp` app role has no CREATEROLE privilege (by design — it only owns
-- the application's own tables), so this must be run once by a Postgres
-- superuser. On this machine that's the native Windows Postgres install's
-- `postgres` superuser account — run this file with psql or pgAdmin logged
-- in as that user, e.g.:
--   psql -U postgres -d erp -f scripts/create_powerbi_reader_role.sql
--
-- Before running: replace CHANGE_ME_STRONG_PASSWORD below with a real
-- password, and give that password to whoever is setting up the Power BI
-- connection (not the app's own erp/erp credentials).

CREATE ROLE powerbi_reader WITH LOGIN PASSWORD 'CHANGE_ME_STRONG_PASSWORD';

GRANT CONNECT ON DATABASE erp TO powerbi_reader;

GRANT USAGE ON SCHEMA core, crm, events, finance, production, sales, warehouse TO powerbi_reader;

GRANT SELECT ON ALL TABLES IN SCHEMA core TO powerbi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA crm TO powerbi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA events TO powerbi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA finance TO powerbi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA production TO powerbi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA sales TO powerbi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA warehouse TO powerbi_reader;

-- New tables are created by the `erp` role as migrations run. Without this,
-- every new migration would need its GRANT SELECT added here by hand — this
-- makes it automatic for any future table in these schemas.
ALTER DEFAULT PRIVILEGES FOR ROLE erp IN SCHEMA core GRANT SELECT ON TABLES TO powerbi_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE erp IN SCHEMA crm GRANT SELECT ON TABLES TO powerbi_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE erp IN SCHEMA events GRANT SELECT ON TABLES TO powerbi_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE erp IN SCHEMA finance GRANT SELECT ON TABLES TO powerbi_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE erp IN SCHEMA production GRANT SELECT ON TABLES TO powerbi_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE erp IN SCHEMA sales GRANT SELECT ON TABLES TO powerbi_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE erp IN SCHEMA warehouse GRANT SELECT ON TABLES TO powerbi_reader;

-- powerbi_reader can SELECT anywhere in these schemas but cannot INSERT,
-- UPDATE, DELETE, or run DDL — it has no write access to the application's
-- data at all.
