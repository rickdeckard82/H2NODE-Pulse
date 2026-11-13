#!/bin/sh
set -eu
# Invoked only on a fresh volume. Runtime never receives the administrator secret.
# The secret travels in the environment, never in argv (visible in /proc/<pid>/cmdline).
PULSE_APP_PASSWORD="$(cat /run/secrets/postgres_password)"
export PULSE_APP_PASSWORD
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=database="$POSTGRES_DB" --set=ON_ERROR_STOP=1 <<'SQL'
\getenv app_password PULSE_APP_PASSWORD
CREATE ROLE pulse LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
ALTER DATABASE :"database" OWNER TO pulse;
ALTER SCHEMA public OWNER TO pulse;
SQL
unset PULSE_APP_PASSWORD
