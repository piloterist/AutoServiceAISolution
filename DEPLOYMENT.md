# Deploying to Timeweb Cloud

This is the current production platform (backend + frontend + managed
PostgreSQL, all in Timeweb's **App Platform** / DBaaS, region `ru-3` = `MSK-1`
Moscow). Railway was the original platform for this project and is
documented in git history only - it was decommissioned once RU-based
visitors reported the site was only reachable through a VPN (Railway's own
IP ranges turned out to be blocked for direct connections from Russian
networks; see `ARCHITECTURE.md`/commit history around September 2026 for the
full story). Do not resurrect anything Railway-specific from old docs
without checking it's still relevant.

## Why Timeweb

Same reasoning as the Yandex.Disk relay module below, at the whole-hosting
level instead of just the 1C integration: some Russian networks (both
"corporate firewall blocking a specific cloud ASN outbound" and, it turned
out, "Russian residential/mobile ISPs blocking that ASN's inbound edge too")
treat foreign-cloud-hosting IP ranges as blocked. Timeweb is a Russian
provider with Russian-registered IP space, which sidesteps that whole class
of problem for a product whose primary customer base is in Russia. See
`ARCHITECTURE.md` for the "cloud-agnostic, pick a provider that reaches your
actual customers" framing - Timeweb is not a hard dependency, just the
current provider.

## Account / API

Dashboard: https://timeweb.cloud. API base URL: `https://api.timeweb.cloud`,
auth via `Authorization: Bearer <token>` - generate a token under **API и
Terraform** in the dashboard. Full OpenAPI spec (useful for finding exact
request shapes):

```
curl -s https://timeweb.cloud/api-docs-data/bundle.json
```

Most of what's below (env vars, redeploys, reboots) can be driven directly
via this REST API with a plain `curl`/`Bearer` token - no separate CLI is
required (there is a `twc` Python CLI, but it wasn't needed here).

**Two things the API cannot do - dashboard only:**
- Connecting a GitHub account/repo (App Platform → Settings → VCS
  providers) - this is an OAuth consent flow, inherently browser-based.
- Attaching a custom ("external") domain to an app (App Platform → app →
  Settings → **Домены** → **Редактировать** → "Внешний домен"). No
  `/domains` sub-resource exists under `/api/v1/apps/{app_id}` as of this
  writing.

## App Platform service settings

Two apps, both deployed the same way, both pointed at
`github.com/piloterist/AutoServiceAISolution`, branch `main`,
auto-deploy on push enabled:

| Setting | Backend | Frontend |
|---|---|---|
| Deploy method | **Docker** tab → **Dockerfile** (not the "Backend"/"Frontend" buildpack tabs - those are for non-Docker language/framework auto-detection, not what we want) | same |
| Root directory | `/backend` (leading slash required by the form) | `/frontend` |
| Region | `ru-3` (Moscow / `MSK-1`) | same - keep app(s) and DB in the same region |
| Preset | smallest available is plenty for current data volume (1 CPU / 1GB RAM / 15GB disk, ~510₽/mo each) | same |

### The one gotcha that will bite you: PORT vs Dockerfile `EXPOSE`

Timeweb's reverse proxy (Caddy) routes to whatever port the Dockerfile's
`EXPOSE` directive declares - **not** whatever you set the `PORT` env var
to. Setting `PORT` to something else just makes the app listen on a port
Caddy isn't forwarding to, which looks exactly like a working-but-invisible
app (deploy log says "App is healthy", external requests 502).

- `backend/Dockerfile` → `EXPOSE 8000` → set `PORT=8000`
- `frontend/Dockerfile` → `EXPOSE 3000` → set `PORT=3000`

### The second gotcha: Next.js standalone binds to the wrong interface

`frontend/Dockerfile`'s prod stage now sets `ENV HOSTNAME=0.0.0.0` -
Next.js's standalone `server.js` binds to `process.env.HOSTNAME`, which
Docker otherwise defaults to the container's own ID/hostname. That only
resolves on the container's *primary* network interface; a container
attached to a second network (this happened specifically right after
attaching an external domain, which appears to move the app onto an
additional internal network) then has the server listening on only one of
its interfaces. If Caddy reaches it via the other one: connection refused →
502, even though Timeweb's own deploy-time healthcheck (apparently routed
differently) reports the app healthy. This was root-caused live via the
app's **Console** tab (a shell into the running container) -
`netstat -ltnp` showed the process bound to one specific container IP, not
`0.0.0.0`. The fix is in the Dockerfile now, so it should not recur - if it
somehow does (e.g. after Timeweb changes something platform-side), the
Console tab + `netstat` is the fastest way to confirm it before chasing
anything else.

### If a redeploy or config change doesn't seem to take effect

Symptom: deploy log shows a clean `Build succeeded` → `App is healthy` →
`Web server Configured` → `Deploy succeeded`, but the app 502s externally
anyway. Try, in order: `PATCH /api/v1/apps/{id}/action/reboot`, then a full
explicit `POST /api/v1/apps/{id}/deploy` (not just relying on
`is_auto_deploy`), then `pause` immediately followed by `resume`. One of
these has always cleared it in practice; if none do, check the Console tab
as above before assuming it's something in this repo's code.

## Required environment variables

Set via `PATCH /api/v1/apps/{app_id}` with a body like
`{"envs": {"KEY": "value", ...}}` - this **replaces** the whole `envs` map,
so always include every key you want kept, not just the one you're
changing. A `GET` on the app only ever shows
`"hidden-by-api-key-policy"` for values, never the real ones back - keep
your own record of what you set.

**Backend:**

| Variable | Value | Notes |
|---|---|---|
| `PORT` | `8000` | must match the Dockerfile's `EXPOSE` - see gotcha above |
| `DATABASE_URL` | `postgresql+psycopg://<user>:<password>@<host>:5432/<db>?sslmode=require` | from the DBaaS cluster's connection details; keep the `+psycopg` scheme |
| `API_TOKEN` | long random secret, unique to this instance | bearer token the 1C/Alpha-Auto integration (via the Yandex relay) and the frontend's server-side calls use |
| `ENVIRONMENT` | `production` | |
| `LOG_LEVEL` | `INFO` | |
| `CORS_ORIGINS` | comma-separated list including the real custom domain, the app's own technical domain, and `http://localhost:3000` for local dev pointed at prod | |
| `REVENUE_STATUSES` | e.g. `Закрыт` | which work-order status(es) count as recognized revenue on the dashboard - client-specific config, not hardcoded (see `ARCHITECTURE.md`) |
| `ENABLE_YANDEX_RELAY` | `true` | see below |
| `YANDEX_DISK_OAUTH_TOKEN` | OAuth token, `disk:read`+`disk:write` scopes | same token the 1C module itself uses |
| `YANDEX_DISK_WATCH_PATH` | `/1c-export` | must match what 1C uploads into |
| `YANDEX_POLL_INTERVAL_SECONDS` | `300` | |

**Frontend:**

| Variable | Value | Notes |
|---|---|---|
| `PORT` | `3000` | must match the Dockerfile's `EXPOSE` |
| `NEXT_PUBLIC_API_URL` | the backend app's own technical domain (`https://<backend-id>.twc1.net`), **not** the custom frontend domain | baked into the client bundle at build time - Timeweb's Docker builder does pick up `envs` as build args, confirmed working |
| `BACKEND_API_TOKEN` | same value as backend's `API_TOKEN` | server-side only, read at runtime by Next.js Server Components |

## Managed PostgreSQL (DBaaS)

Created via dashboard (the `admin`/`instance` request shape for
`POST /api/v1/databases` isn't fully documented in the OpenAPI bundle - use
the dashboard's own "generate cURL" button under the create-cluster form if
you need to script this later). Postgres 16, region matching the apps.
Connection needs `sslmode=require` (or `sslmode=verify-full` with Timeweb's
CA cert at `https://st.timeweb.com/cloud-static/ca.crt`, not currently
used). The free tier only allows one DB + one user per cluster - rename the
defaults (`gen_user`/`default_db`) to something meaningful instead of
creating new ones.

## Applying Alembic migrations

No pre-deploy-command equivalent was found in Timeweb's app config (unlike
Railway's `preDeployCommand`). What worked: build the backend image locally
and run Alembic against the remote database directly, pointed at whatever
`DATABASE_URL`/`API_TOKEN` you set on the app (Settings requires
`api_token` even just to import the app, so it must be passed too even
though Alembic itself doesn't use it):

```bash
docker build -t autoservice-backend-migrate ./backend
docker run --rm \
  -e DATABASE_URL="postgresql+psycopg://<user>:<password>@<host>:5432/<db>?sslmode=require" \
  -e API_TOKEN="<same value as the app's API_TOKEN>" \
  autoservice-backend-migrate alembic upgrade head
```

Confirm it worked either from the Alembic output itself (`Running upgrade
... -> <revision>`) or by calling the real API afterward
(`GET /api/v1/work-orders` should return `200` with an empty list, not a
"relation does not exist" error).

## Custom domain

1. App Platform → the frontend app → **Settings** → **Домены** →
   **Редактировать** → choose **Внешний домен**, enter it, save. The panel
   then shows an IP to point an A record at.
2. At your DNS host (not Cloudflare - see the "Why Timeweb" note above,
   proxying through Cloudflare's edge turned out to be part of the original
   RU-reachability problem too), create an A record: `@` → that IP.
3. Wait for it to actually resolve (`nslookup yourdomain.ru 8.8.8.8` from
   outside your own network/ISP, to rule out local caching) before doing
   anything else in Timeweb's panel - the panel's own hint says as much.
4. **Only after step 3 resolves**, go back and hit Save in Timeweb's
   domain form. This triggers a redeploy. If the app 502s afterward, see
   "If a redeploy or config change doesn't seem to take effect" above -
   binding/unbinding a domain is exactly the trigger that surfaced the
   HOSTNAME gotcha in the first place.

If the domain's registrar is REG.RU and it was previously delegated
elsewhere (Cloudflare, in this project's case): switch the domain's
nameservers back to REG.RU's own (`ns1.reg.ru` / `ns2.reg.ru`) *before*
adding the A record - the DNS-records section of REG.RU's panel is
otherwise inert (accepts and saves the record, but it never actually
resolves) until that delegation change has propagated to the .ru registry,
which can take anywhere from minutes to ~24h. You can add the A record
immediately regardless (it just sits inert until the NS switch lands) - no
need to wait to do that part.

## Optional module: Yandex.Disk relay (firewall fallback)

Unchanged in mechanism from the original design - only which backend polls
the folder changes when switching platforms. Some client 1C environments
cannot reach a hosted backend's domain directly (seen with the Pan Motors /
5Systems hosting: their outbound firewall blocked direct HTTPS to Railway's
IP ranges specifically, while Yandex's own infrastructure was reachable).
Instead of 1C calling the backend API directly, it uploads its export JSON
to a folder on Yandex.Disk through Yandex's **REST API**
(`cloud-api.yandex.net`, OAuth token) - **not WebDAV** (that requires a paid
Yandex.Disk plan). This backend polls the folder on a timer and imports any
new file through the exact same `process_work_order_import` path the direct
API uses, then moves the file into a `processed/` subfolder.

Runs as a plain `asyncio` background task inside the existing backend
process (started from the FastAPI `lifespan` handler in `app/main.py`) - no
separate service to deploy. Off by default; the env vars are listed in the
table above.

**Only one backend instance should have `ENABLE_YANDEX_RELAY=true` pointed
at a given watch path at a time** - two pollers racing on the same folder
can end up with only one of them actually importing a given file (whichever
wins the race moves it to `processed/` first). This mattered directly
during the Railway → Timeweb cutover: Railway's relay had to be switched off
before Timeweb's was switched on, to make sure the next 1C export actually
landed in the right database.

Use a **dedicated** Yandex account for this, not a personal one, so access
can be revoked/rotated independently or handed off. 1C authenticates to the
REST API with the same `YANDEX_DISK_OAUTH_TOKEN` value configured on the
backend (pasted directly into the 1C module - see
`1c/TestExportOrders.bsl`) - no separate login/password needed.

## What stays local

`docker-compose.yml` and `.env` are unaffected by any of the above - local
development continues to run exactly as before via `docker compose up`.
