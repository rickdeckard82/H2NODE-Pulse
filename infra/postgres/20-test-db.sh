#!/bin/sh
set -eu
# Mounted only by compose.test.yaml, never by the application database.
psql -v ON_ERROR_STOP=1 --username postgres --dbname pulse <<'SQL'
CREATE DATABASE test_pulse OWNER pulse;
SQL
