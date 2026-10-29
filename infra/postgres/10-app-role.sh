#!/bin/sh
set -eu
# Invoked only on a fresh volume. Runtime never receives the administrator secret.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=app_password="$(cat /run/secrets/postgres_password)" \
  --set=database="$POSTGRES_DB" --set=ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE pulse LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
ALTER DATABASE :"database" OWNER TO pulse;
ALTER SCHEMA public OWNER TO pulse;
SQL
