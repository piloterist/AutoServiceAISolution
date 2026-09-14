# AutoService Platform

A tenant-per-instance (single-tenant hosted SaaS) platform for auto service
businesses, built around the **Work Order** as the central entity. One
codebase, deployed separately per client (own containers, own PostgreSQL
database, own configuration) - see [ARCHITECTURE.md](ARCHITECTURE.md).

Pan Motors is the first pilot client, not a special case in the code.

## Stack

- **Backend:** Python, FastAPI, SQLAlchemy 2.x, Pydantic, Alembic
- **Database:** PostgreSQL
- **Frontend:** Next.js, TypeScript
- **Dev environment:** Docker Compose

## Project layout

```
backend/     FastAPI app (modular monolith), Alembic migrations, tests
frontend/    Next.js application shell
infra/       Non-application infra assets (DB init scripts, deployment notes)
docker-compose.yml
.env.example
ARCHITECTURE.md
```

## Quick start (local development)

```bash
cp .env.example .env      # edit values if you like; defaults work out of the box
docker compose up --build
```

This starts:

| Service  | URL                    |
|----------|------------------------|
| frontend | http://localhost:3000  |
| backend  | http://localhost:8000  |
| postgres | localhost:5432 (loopback only) |

First run: apply database migrations once the containers are up:

```bash
docker compose exec backend alembic upgrade head
```

## Everyday commands

```bash
# Start everything
docker compose up

# Stop everything
docker compose down

# Backend shell
docker compose exec backend bash

# Create a new migration after changing models
docker compose exec backend alembic revision --autogenerate -m "message"

# Apply migrations
docker compose exec backend alembic upgrade head

# Run backend tests
docker compose exec backend pytest

# Run backend tests with coverage
docker compose exec backend pytest --cov=app

# Lint / format backend
docker compose exec backend ruff check .
docker compose exec backend ruff format .

# Frontend lint
docker compose exec frontend npm run lint
```

## Integration API (1C / Alpha-Auto)

```bash
curl -X POST http://localhost:8000/api/v1/import/work-orders \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "alpha-auto",
    "branch": "kahovka",
    "entity": "work_orders",
    "exported_at": "2026-09-13T10:00:00",
    "batch_id": "20260913-100000",
    "records": [
      {
        "number": "PS00010196",
        "date": "2026-09-12T18:38:09",
        "customer": "Example Customer",
        "car": "VW TIGUAN VIN XXXXXXXXX",
        "amount": 18500
      }
    ]
  }'
```

Sending the same `number` again updates the existing Work Order (upsert on
`source_system` + `external_number`) instead of creating a duplicate.

## Inspecting data

```bash
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c 'select external_number, customer_name, amount, updated_at from work_orders;'
```

## Security notes

- No credentials are hardcoded anywhere in the code.
- All secrets (`API_TOKEN`, DB credentials) come from environment variables;
  `.env` is git-ignored, `.env.example` contains placeholders only.
- PostgreSQL's port is published to `127.0.0.1` only - it is never intended
  to be reachable from the public internet.
- `API_TOKEN` is per-instance: each client deployment sets its own value.

## Production

The backend only requires a reachable PostgreSQL via `DATABASE_URL` - it does
not assume Docker Compose or a co-located database, so it can run against a
managed PostgreSQL service or on-premise for an enterprise client. See
[infra/README.md](infra/README.md) for deployment notes.

## Further reading

- [ARCHITECTURE.md](ARCHITECTURE.md) - design decisions and extension points
  for future client-specific customization (workflows, KPIs, feature flags).
- [DEPLOYMENT.md](DEPLOYMENT.md) - deploying to Timeweb Cloud (env vars,
  service settings, migration mechanism).
