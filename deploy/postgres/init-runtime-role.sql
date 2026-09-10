-- Development only. The Postgres image runs this once, on a fresh data volume, as the
-- Compose superuser against the Compose database. It creates the restricted runtime
-- login that DI_DATABASE_URL uses by default, so `make db-up && make migrate` is enough.
-- Production provisions di_migrate and di_app with managed credentials; see docs/pipeline.md.
CREATE ROLE di_app LOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT PASSWORD 'di_app';
GRANT USAGE ON SCHEMA public TO di_app;
-- Tables are created later by migrations run as the current (superuser) role; this makes
-- every such table readable and writable by di_app without a manual GRANT afterwards.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO di_app;
