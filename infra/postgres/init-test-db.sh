#!/bin/sh
# Runs automatically on first container start (docker-entrypoint-initdb.d
# convention). Creates a second, dedicated database for the backend test
# suite so tests never run against the application's real data.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE "${POSTGRES_DB}_test"'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${POSTGRES_DB}_test')\gexec
EOSQL
