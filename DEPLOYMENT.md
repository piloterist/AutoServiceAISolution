# Deploying the backend to Railway

This covers **backend only**. The frontend stays local for now and is not
deployed to Railway at this stage.

## Service settings (Railway dashboard, when creating/configuring the backend service)

| Setting | Value |
|---|---|
| Root Directory | `backend` |
| Builder | Dockerfile |
| Dockerfile Path | `Dockerfile` (relative to Root Directory, so `backend/Dockerfile`) |
| Start Command | leave empty - the Dockerfile's `CMD` already runs `uvicorn` bound to `$PORT` |
| Healthcheck Path | `/health` |

A `backend/railway.json` is committed with these deploy settings
(build/healthcheck/restart policy) so most of this is picked up automatically
once Root Directory is set to `backend`; the table above is what to check/set
by hand if Railway doesn't read it.

## Required environment variables (backend service)

Set these in the Railway backend service's **Variables** tab. None of them
exist in the code or in git - they must be entered per deployment:

| Variable | Value | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://<user>:<password>@<host>:<port>/<database>` | **Must** keep the `+psycopg` driver suffix (see "Connecting to the Railway Postgres" below) - do not reuse Railway Postgres's own `DATABASE_URL` variable as-is. |
| `API_TOKEN` | a long random secret, unique to this instance | This is the bearer token the 1C/Alpha-Auto integration will send. Generate with e.g. `openssl rand -hex 32`. Never reuse the local dev value. |
| `ENVIRONMENT` | `production` | |
| `LOG_LEVEL` | `INFO` | |
| `CORS_ORIGINS` | leave at default for now, or set to the frontend's future URL once it exists | comma-separated if more than one origin |

Do **not** set `PORT` yourself - Railway injects it automatically and the
Dockerfile's `CMD` reads it (`--port ${PORT:-8000}`, falling back to 8000
only when `PORT` is absent, e.g. local `docker run`).

`TEST_DATABASE_URL` is not needed in Railway - it's only used by the local
test suite.

## Connecting the backend service to the existing Railway PostgreSQL

Railway's Postgres plugin exposes its own reference variables (`PGHOST`,
`PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`, and a `DATABASE_URL` using the
plain `postgresql://` scheme). Our backend uses SQLAlchemy with the
**psycopg 3** driver (`psycopg[binary]`, not `psycopg2`), which requires the
`postgresql+psycopg://` scheme - the bare `postgresql://` that Railway
generates for its own `DATABASE_URL` variable will make SQLAlchemy try to
load `psycopg2`, which is not installed, and the app will fail to start.

So in the backend service's Variables tab, set `DATABASE_URL` as a **new**
variable built from a reference to the Postgres service, with the scheme
corrected:

```
DATABASE_URL=postgresql+psycopg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}
```

(Adjust `Postgres` to whatever the Postgres service is actually named in the
Railway project - that's the reference prefix Railway uses.) Using Railway's
variable references (rather than copy-pasting the resolved values) means the
value stays correct if the Postgres service ever changes host/port/creds.

## Applying Alembic migrations

The tables in Railway's Postgres do not exist yet and must be created by the
existing Alembic migration(s) - never by hand.

**Do not** bake `alembic upgrade head` into the container's normal start
command (i.e. don't do `alembic upgrade head && uvicorn ...` as the
always-run start command). If Railway ever runs more than one instance/
replica, or restarts the container automatically, every restart would
re-attempt the migration concurrently - harmless once already applied, but
unnecessary risk for no benefit.

Two supported ways to run migrations against Railway Postgres once
`DATABASE_URL` is set on the backend service, **whenever you're ready** (not
now - there's no connection to Railway yet from this environment):

1. **Preferred - Railway's pre-deploy step.** `backend/railway.json` already
   declares `deploy.preDeployCommand: "alembic upgrade head"`. If your
   Railway project version supports this field, it runs once per deploy,
   before the new instance starts serving traffic, separately from the app
   process - the safe place for migrations. Confirm in the Railway dashboard
   (Service -> Settings -> Deploy) that a "Pre-Deploy Command" is shown and
   picked up; if your Railway version doesn't support it, use option 2.

2. **Manual, always works.** From a machine with the Railway CLI, linked to
   this project:
   ```bash
   railway link            # select this project/service once
   railway run alembic upgrade head
   ```
   `railway run` executes the command locally but with the linked service's
   real environment variables injected, so it reaches the real
   `DATABASE_URL` without you ever pasting the credential anywhere. This can
   also be run from inside the deployed service via the Railway dashboard's
   "Shell" if available.

Either way, this is a deliberate, explicit step - not something to run
automatically as part of this task.

## Health check

`GET /health` requires no authentication and does not touch the database,
so it is safe to point Railway's health check at it - it reflects only "the
process is up", not "the database is reachable", which avoids restart loops
from a transient DB blip. It already matches what `backend/railway.json`
configures (`healthcheckPath: /health`).

## What stays local

The frontend, `docker-compose.yml`, and `.env` are unaffected by any of the
above - local development continues to run exactly as before via
`docker compose up`.
