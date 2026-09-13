# infra

Infrastructure-support assets that are not application code:

- `postgres/init-test-db.sh` - creates the `<POSTGRES_DB>_test` database used
  by the backend test suite. Mounted into the Postgres container's
  `docker-entrypoint-initdb.d/` in `docker-compose.yml`.

## Production notes

- The application does not assume Docker Compose in production. The backend
  only needs `DATABASE_URL` pointing at any reachable PostgreSQL instance
  (self-hosted, or a managed service such as RDS/Cloud SQL/Azure Database for
  PostgreSQL).
- Backend and frontend are plain container images (see each service's
  `Dockerfile`) and can run on any container platform (Compose, a single VM,
  ECS, Cloud Run, on-prem Docker/Podman, etc.) - no Kubernetes requirement.
- PostgreSQL must not be exposed directly to the public internet; only the
  backend service should be able to reach it (private network/security group).
- Each client instance is a separate deployment: its own containers, its own
  database, its own environment variables (`API_TOKEN`, `DATABASE_URL`,
  `CORS_ORIGINS`, etc.). There is no shared multi-tenant database.
