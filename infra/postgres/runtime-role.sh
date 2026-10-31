#!/bin/sh
set -eu
export PGPASSWORD="$(cat /run/secrets/postgres_admin_password)"
export PULSE_RUNTIME_PASSWORD="$(cat /run/secrets/postgres_runtime_password)"
psql -X --set=ON_ERROR_STOP=1 --file=/opt/pulse/runtime-grants.sql
unset PGPASSWORD PULSE_RUNTIME_PASSWORD
