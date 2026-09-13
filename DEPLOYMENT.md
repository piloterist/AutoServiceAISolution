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

Tables are created by the existing Alembic migration(s) via a Railway
**pre-deploy command** (`alembic upgrade head`) - never by hand, and never
baked into the container's normal start command (`alembic upgrade head &&
uvicorn ...`), since that would re-run the migration on every restart/replica
concurrently - harmless once applied, but unnecessary risk for no benefit.

**What actually worked, in practice (do this, not the two things below it):**
the repo's `backend/railway.json` is Railway's older, now-deprecated
"Config as Code" mechanism - a service created after ~2026-08-28 that never
used it before cannot enable it, so this file is currently inert for a fresh
service (kept anyway - harmless, and this may change). The Railway
dashboard's own `Settings -> Deploy -> Add pre-deploy step` field also
**silently failed to persist** when tried once (confirmed by pulling the
live config back down - it came back empty even after saving "successfully"
in the UI). The mechanism that did work is Railway's **current CLI-based
IaC** (`railway config`, backed by `.railway/railway.ts` - unrelated to the
deprecated repo-committed `railway.json`/`railway.toml` files despite the
similar name):

```bash
railway link                      # once, selects this project/service
railway config pull                # imports live config into .railway/railway.ts
# edit .railway/railway.ts: add `preDeployCommand: "alembic upgrade head"`
# to the service's options
railway config plan                 # preview - should show exactly that one change
railway config apply --yes
railway redeploy -s AutoServiceAISolution -y   # re-run the pre-deploy step now
```

`.railway/` is gitignored (it can hold decrypted-looking `preserve()`
placeholders for secrets, never real values, but keep it local regardless).

On Windows, `railway config plan/apply` may fail with `This version of
railway/iac requires Railway CLI X.Y.Z or newer` even when the installed CLI
is newer - this is a real bug in how the CLI reports its own path to the
bundled Node evaluator via the `_` env var on Windows. Workaround: invoke the
actual `railway.exe` by its full path (not the bare `railway` shim on PATH),
e.g. `"$(npm root -g)/@railway/cli/bin/railway.exe" config plan` - bash then
sets `_` to that real path itself and the check passes.

To verify migrations actually ran: check `railway logs -s <service>
--deployment --lines 100 --latest` for Alembic's `Running upgrade ->
<revision>` line, or just call the real API (`POST
/api/v1/import/work-orders`) and confirm it returns `200` instead of a
"relation does not exist" error - that's the most reliable proof the tables
exist.

## Health check

`GET /health` requires no authentication and does not touch the database,
so it is safe to point Railway's health check at it - it reflects only "the
process is up", not "the database is reachable", which avoids restart loops
from a transient DB blip. It already matches what `backend/railway.json`
configures (`healthcheckPath: /health`).

## Optional module: Yandex.Disk relay (firewall fallback)

Some client 1C environments cannot reach this backend's domain directly -
seen with the Pan Motors / 5Systems hosting, whose outbound firewall blocks
HTTPS to arbitrary "cloud hosting" IP ranges (confirmed: Railway's own IP is
blocked, `api.github.com` and Cloudflare's `1.1.1.1` are not - looks like a
block on cloud/VPS-hosting ASNs specifically, not a strict default-deny
policy). The first fix to try for that is fronting the backend with a custom
domain through Cloudflare (widely-allowed CDN IP ranges) - see git history /
ARCHITECTURE.md for that path. This module is the fallback for when even
that does not clear the firewall.

Instead of 1C calling this API directly, it uploads its export JSON to a
folder on Yandex.Disk through Yandex's **REST API** (`cloud-api.yandex.net`,
OAuth token) - **not WebDAV**: WebDAV (`webdav.yandex.ru`) was tried first
and Yandex rejected it with `402 Payment Required: WebDAV is not available
for the free tariff` - WebDAV specifically requires a paid Yandex.Disk plan,
while the REST API does not. So 1C uses the same OAuth-token auth as this
backend's own poller, not a separate login+app-password pair. This backend
polls the folder on a timer and imports any new file through the exact same
`process_work_order_import` path the direct API uses - same validation,
same idempotent upsert, same `ImportBatch` audit trail - then moves the file
into a `processed/` subfolder so it is not re-imported (re-importing it
would be harmless, just wasted work, since the upsert is idempotent).

Runs as a plain `asyncio` background task inside the existing backend
process (started from the FastAPI `lifespan` handler in `app/main.py`) - no
separate service, queue, or scheduler to deploy. Off by default; only turn it
on for a client instance that actually needs it.

**Environment variables** (backend service):

| Variable | Value |
|---|---|
| `ENABLE_YANDEX_RELAY` | `true` to turn it on |
| `YANDEX_DISK_OAUTH_TOKEN` | OAuth token for the dedicated Yandex account, scopes `disk:read` + `disk:write` (get one at https://oauth.yandex.ru, or via the quick test-token flow at https://yandex.ru/dev/disk/poligon/) |
| `YANDEX_DISK_WATCH_PATH` | folder to watch, default `/1c-export` (must match what 1C uploads into) |
| `YANDEX_POLL_INTERVAL_SECONDS` | default `300` (5 min) |

Use a **dedicated** Yandex account for this, not a personal one - so access
can be revoked/rotated independently or handed off. 1C authenticates to the
REST API with the same `YANDEX_DISK_OAUTH_TOKEN` value configured on the
backend (pasted into the 1C module directly - see `1c/TestExportOrders.bsl`)
- no separate login/password needed.

## What stays local

The frontend, `docker-compose.yml`, and `.env` are unaffected by any of the
above - local development continues to run exactly as before via
`docker compose up`.
