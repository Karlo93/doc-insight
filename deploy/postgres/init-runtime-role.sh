#!/bin/sh
set -eu
# psql literal quoting keeps generated passwords out of executable SQL syntax.
psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --set=runtime_password="${DI_DB_RUNTIME_PASSWORD:?runtime password required}" <<'SQL'
CREATE ROLE di_app LOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT PASSWORD :'runtime_password';
GRANT USAGE ON SCHEMA public TO di_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO di_app;
SQL
