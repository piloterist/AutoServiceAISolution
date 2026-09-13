# CLAUDE.md — AutoServiceAISolution Full Handoff

This file is the authoritative project context for Claude Code / VS Code.

Read this file first before making architectural or implementation changes.

The goal is to continue the project without requiring the operator to manually copy context from previous ChatGPT conversations.

IMPORTANT:
- Do not invent missing credentials.
- Do not commit secrets.
- Do not redesign the architecture silently.
- Preserve working behavior unless there is a clear reason to change it.
- The operator is not a professional 1C developer, so prefer complete replacement-ready code blocks and small verifiable steps for 1C tasks.

---

# 1. PRODUCT GOAL

We are building a **replicable commercial browser-based product for automotive service businesses**.

This is NOT a one-off internal tool for Pan Motors.

Pan Motors is the first pilot/customer and source of real operational requirements.

The final product should eventually support:

- Dashboard
- Work Orders
- Kanban
- Current vehicles / repair cases
- Workshop workload
- Employee efficiency
- Labor operations / labor hours
- Parts
- Costs
- Revenue
- Margin
- Profitability
- Historical analytics
- Financial analytics
- P&L
- KPI
- Operational alerts
- Configurable workflows
- Potential AI/analytics features later

## Central business entity

**Work Order / Заказ-наряд** is the aggregate root and the core business entity.

Reason:
- revenue is tied to it;
- costs are tied to it;
- labor is tied to it;
- parts are tied to it;
- employees are tied to it;
- vehicle is tied to it;
- status/workflow is tied to it;
- profitability and reporting are tied to it.

Vehicle is NOT the aggregate root.

Do not build the product around Vehicle as the primary entity.

---

# 2. COMMERCIAL / DEPLOYMENT MODEL

Chosen model:

## SINGLE-TENANT HOSTED SAAS

For each customer:

- separate application instance;
- separate PostgreSQL database;
- own configuration;
- optional enabled modules / feature flags;
- same product codebase;
- no customer-specific forks.

Example:

Client A:
- backend A
- frontend A
- PostgreSQL A
- config A

Client B:
- backend B
- frontend B
- PostgreSQL B
- config B

The system is hosted and managed by us by default.

Why this model was chosen:

- better physical isolation of customer data;
- easier to explain security to automotive businesses;
- allows business-process differences between customers;
- supports subscription model well;
- backend/IP remains under our control;
- avoids a giant shared multi-tenant DB;
- still allows centralized releases from one codebase.

## Important customization principle

Different customers may have different:

- Kanban stages;
- statuses;
- workflows;
- KPI formulas;
- departments;
- business roles;
- operational logic;
- enabled modules.

These differences should be handled through:

- configuration;
- workflow definitions;
- feature flags;
- metric definitions;
- optional modules;
- client-specific settings.

Do NOT hardcode Pan Motors-specific logic into the core.

Do NOT create separate code forks per customer.

## Future enterprise option

The product must remain portable enough to deploy the same stack on-premise/private cloud for enterprise customers if necessary.

Cloud-first, but provider-independent.

---

# 3. SUBSCRIPTION / IP MODEL

Primary hosted model supports subscription naturally.

Because backend remains in our infrastructure:
- customer uses the service;
- source code is not handed over;
- subscription/access can be managed centrally.

Possible future on-premise version:
- separate licensing mechanism;
- periodic license validation;
- grace period;
- optional read-only behavior if license expires.

This licensing system is NOT part of current MVP.

---

# 4. TECHNICAL STACK

## Backend

- Python
- FastAPI
- SQLAlchemy 2.x
- Pydantic
- Alembic
- modular monolith

Current SQLAlchemy style:
- synchronous sessions/routes
- intentional simplicity
- no async conversion unless measured need appears

## Database

- PostgreSQL
- money uses NUMERIC/Decimal, never float

## Frontend

- Next.js
- TypeScript
- App Router

## Development

- Docker Compose
- Git
- GitHub

## Integration

- REST JSON over HTTPS
- Bearer API token
- 1C pushes data outward

## Explicitly avoid premature complexity

Do NOT add unless justified:
- Kubernetes
- Kafka
- RabbitMQ
- Redis
- microservices
- CQRS
- Event Sourcing

---

# 5. CLOUD PROVIDER STRATEGY

Current staging provider:

## Railway

Why:
- fast to provision;
- GitHub deployment;
- Docker-friendly;
- managed PostgreSQL;
- public HTTPS backend;
- simple env-var wiring.

Railway is NOT a hard product dependency.

Other valid future providers:
- Timeweb Cloud
- other managed cloud providers
- VPS
- private cloud
- enterprise on-premise

Timeweb Cloud is specifically considered a strong candidate for Russian customers.

Product code must remain cloud-agnostic.

---

# 6. GITHUB / REPOSITORY STATE

GitHub repository:

https://github.com/piloterist/AutoServiceAISolution.git

Branch:

main

Initial commit:

9e8132397c28ed3c6bb729bcbe4cbab105fab25d

Recorded author:

pkulikov <pkulikov@navicons.com>

Remote:

origin https://github.com/piloterist/AutoServiceAISolution.git

Status after push:

- local main tracks origin/main
- working tree clean
- `.env` ignored
- no known secrets committed

---

# 7. CURRENT PROJECT STRUCTURE

Current project structure reported by coding agent:

```text
AutoSericeseAISoulution_v1.0/
├── backend/
│   ├── app/
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── api/
│   │   ├── services/
│   │   └── main.py
│   ├── alembic/
│   ├── tests/
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── railway.json
├── frontend/
├── infra/
├── docker-compose.yml
├── .env.example
├── .env                  # local only, gitignored
├── ARCHITECTURE.md
├── DEPLOYMENT.md
└── README.md
```

Claude Code should inspect the actual repository and treat that as source of truth if structure evolved.

---

# 8. LOCAL DEVELOPMENT STATE

Local Docker Compose stack has been fully tested end-to-end.

Containers:

- PostgreSQL — healthy
- FastAPI backend — port 8000
- Next.js frontend — port 3000

Local backend:

http://localhost:8000

Local frontend:

http://localhost:3000

Backend health:

```text
GET /health
```

returns:

```json
{"status":"ok"}
```

PostgreSQL locally was bound only to:

127.0.0.1:5432

not publicly exposed.

---

# 9. TEST STATUS

Backend tests:

- health endpoint
- import without token -> unauthorized
- import with wrong token -> unauthorized
- successful WorkOrder import
- repeat import updates instead of duplicate
- ImportBatch audit record

Result:

6 passed

Also:

- `ruff check` clean
- `ruff format --check` clean
- frontend lint clean

Real local E2E import was tested:
- first import -> inserted=1
- repeat import with changed amount -> updated=1
- only one WorkOrder row remains
- updated amount persisted
- ImportBatch records created for each attempt

---

# 10. BACKEND DATA MODEL

## WorkOrder

Current intentionally minimal model:

- id: UUID primary key
- external_number: required string
- source_system: string, default `"alpha-auto"`
- source_key: nullable string
- document_date: datetime
- customer_name: nullable string
- vehicle_description: nullable string
- amount: NUMERIC(14,2)
- source_updated_at: nullable datetime
- raw_payload: JSONB nullable
- created_at
- updated_at

Current unique constraint:

```text
(source_system, external_number)
```

This is provisional.

Important future task:
Find stable Alpha-Auto document identifier:
- GUID
- reference
- immutable key
- internal document identifier

Then consider moving source identity toward `source_key`.

## ImportBatch

Fields include:

- id UUID
- batch_id
- source
- entity
- branch nullable
- exported_at
- received_at
- records_received
- records_inserted
- records_updated
- status
- error_message nullable

Purpose:
Every 1C upload attempt must be traceable.

---

# 11. UPSERT IMPLEMENTATION DETAILS

Current PostgreSQL UPSERT uses:

`INSERT ... ON CONFLICT DO UPDATE`

Conflict target:

`(source_system, external_number)`

Insert-vs-update differentiation uses PostgreSQL:

`RETURNING xmax = 0`

Important implementation detail already discovered/fixed:

Using ORM-enabled:

`pg_insert(WorkOrder)`

caused arbitrary RETURNING columns to be filtered.

Working approach uses:

`WorkOrder.__table__`

at SQLAlchemy Core level.

Also:

ORM `onupdate` did not fire during raw ON CONFLICT update.

Therefore:

`updated_at = func.now()`

is explicitly included in update SET.

Do not casually refactor this back to ORM-style without preserving behavior.

---

# 12. CURRENT IMPORT API CONTRACT

Endpoint:

```text
POST /api/v1/import/work-orders
```

Auth:

```text
Authorization: Bearer <API_TOKEN>
```

Content-Type:

```text
application/json
```

Expected body:

```json
{
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
}
```

Expected response:

```json
{
  "status": "ok",
  "received": 1,
  "inserted": 1,
  "updated": 0,
  "batch_id": "20260913-100000"
}
```

API token comes only from env vars.

---

# 13. RAILWAY PREPARATION

Railway account exists.

Railway project exists.

Railway PostgreSQL service has already been created and is online.

No tables were manually created in Railway PostgreSQL.

Schema must be created by Alembic migrations.

Backend has NOT yet been deployed to Railway at the time of this handoff.

## Backend Dockerfile preparation

Dockerfile was updated so that uvicorn:

- listens on `0.0.0.0`
- uses `${PORT:-8000}`
- uses Railway-provided PORT in cloud
- defaults to 8000 locally
- starts via shell `exec` so uvicorn becomes PID 1
- receives SIGTERM correctly

## backend/railway.json

Contains:
- Dockerfile build
- `/health` health check
- restart policy
- preDeploy command:

```text
alembic upgrade head
```

## Railway backend settings planned

Root Directory:

```text
backend
```

Dockerfile Path:

```text
Dockerfile
```

Start Command:

leave empty

Healthcheck:

```text
/health
```

## Railway env vars

Need:

- `DATABASE_URL`
- `API_TOKEN`
- `ENVIRONMENT=production`
- `LOG_LEVEL=INFO`

Do NOT manually define:
- `PORT`
- `TEST_DATABASE_URL`

## psycopg3 URL requirement

Project uses psycopg 3.

Backend expects:

```text
postgresql+psycopg://...
```

Railway's native DB URL may be `postgresql://...`.

Suggested backend variable:

```text
DATABASE_URL=postgresql+psycopg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}
```

Replace service name if not exactly `Postgres`.

Immediate next cloud goal:

1. create Railway backend service from GitHub repo;
2. configure root dir/env;
3. deploy;
4. run Alembic via preDeploy;
5. verify public `/health`;
6. then test real 1C -> Railway backend -> Railway PostgreSQL.

---

# 14. 1C / ALPHA-AUTO ENVIRONMENT — FULL HISTORY

System:

- 1C:Enterprise
- Alpha-Auto / 5S AUTO
- hosted by 5Systems
- 1C platform version: 8.3.16.1148
- thick client

1C executable:

```text
C:\Program Files (x86)\1cv8\8.3.16.1148\bin\1cv8.exe
```

User profile path on remote server observed as:

```text
D:\Users\U036009
```

---

# 15. 1C INFORMATION BASE CONNECTION

1C base config was retrieved from:

```text
%APPDATA%\1C\1CEStart\ibases.v8i
```

Contents:

```text
[5S AUTO]
Connect=Srvr="ONEC-6";Ref="U036-alfa";
ID=d9a5c0c5-84ab-452e-8b62-5478d262c90e
OrderInList=16384
Folder=/
OrderInTree=16384
External=1
App=Auto
WA=1
Version=8.3
DefaultApp=ThickClient
```

Therefore:

1C server:

```text
ONEC-6
```

1C base:

```text
U036-alfa
```

Default client:

ThickClient

---

# 16. 1C USER

Known 1C user:

```text
Пан Станислав Вячеславович
```

The 1C password exists and was successfully used.

DO NOT store it in repo or this file.

---

# 17. RDP ACCESS TO 5SYSTEMS

RDP server:

```text
dc1.5systems.ru
```

Observed resolved IP:

```text
178.69.191.141
```

Port:

```text
16139
```

Windows/RDP user:

```text
5S\U036009
```

Password exists but is intentionally not included.

Connectivity test from development PC:

```powershell
Test-NetConnection dc1.5systems.ru -Port 16139
```

Result:

```text
TcpTestSucceeded : True
```

---

# 18. RDP CONNECTION PROBLEM AND FIX

Initial RDP attempts failed before credential prompt.

Error:

```text
Error code: 0x3000008
Extended error code: 0x0
```

RDP event log showed the real issue.

Relevant log:

```text
Microsoft-Windows-TerminalServices-RDPClient/Operational
```

Events included:

```text
Gateway servers list - Server(dc1.5systems.ru)
Gateway connection disconnected
AAEventTunnelOnConnectedFailed
Gateway Error 0x80075A0F
```

Root cause:
Windows RDP client was auto-detecting/using RD Gateway when it should not.

Fix:

```text
mstsc
→ Show Options
→ Advanced
→ Settings (Connect from anywhere)
→ Do not use an RD Gateway server
```

After selecting:

```text
Do not use an RD Gateway server
```

direct RDP worked.

---

# 19. RDP FILES

A working full desktop RDP file exists:

```text
Alpha_Auto_1C.rdp
```

Behavior:
- full remote desktop
- NOT RemoteApp
- server `dc1.5systems.ru:16139`
- username `5S\U036009`
- gateway disabled

An earlier file supplied by 5Systems was configured as RemoteApp:
- launched only 1C
- `remoteapplicationprogram:s:||1cestart`
- `remoteapplicationmode:i:1`

That RemoteApp file was intentionally rejected for development because full desktop access is needed.

---

# 20. RDP CLIPBOARD PROBLEM AND FIX

Clipboard copy/paste over RDP stopped working once.

Fix:

1. kill process:
   `rdpclip.exe`
2. start:
   `rdpclip`

Clipboard immediately worked again.

RDP Local Resources → Clipboard is enabled.

---

# 21. CONFIGURATOR / 1C DEVELOPMENT FILE

External processing created:

```text
TestExportOrders.epf
```

This file is the current 1C prototype used for experimentation.

It is edited via 1C Configurator.

---

# 22. FIRST SUCCESSFUL 1C QUERY

The first working query returned the last 10 Work Orders.

Fields:

- Number
- Date
- Counterparty/customer
- Vehicle
- Document amount

Confirmed working query:

```1c
Запрос.Текст =
"ВЫБРАТЬ ПЕРВЫЕ 10
| ЗаказНаряд.Номер КАК Номер,
| ЗаказНаряд.Дата КАК Дата,
| ЗаказНаряд.Контрагент КАК Контрагент,
| ЗаказНаряд.Автомобиль КАК Автомобиль,
| ЗаказНаряд.СуммаДокумента КАК СуммаДокумента
|ИЗ
| Документ.ЗаказНаряд КАК ЗаказНаряд
|
|УПОРЯДОЧИТЬ ПО
| ЗаказНаряд.Дата УБЫВ";
```

This query is known-good in Alpha-Auto.

---

# 23. FIRST UI OUTPUT

Initial prototype looped through the result and used:

```1c
Сообщить(...)
```

to display the 10 records in 1C UI.

This confirmed data access from Alpha-Auto.

---

# 24. CSV EXPORT PROTOTYPE

The EPF was then modified to write CSV.

Output file:

```text
C:\Temp\TestExportOrders.csv
```

Columns:

```text
Номер;Дата;Контрагент;Автомобиль;СуммаДокумента
```

This worked.

This CSV transport is now considered only:
- a diagnostic fallback;
- a prototype.

The preferred final architecture is direct JSON over HTTPS.

---

# 25. EPF AUTO-RUN BEHAVIOR

Originally export logic was bound to:

```1c
Процедура КнопкаВыполнитьНажатие(Кнопка)
```

A form-open handler was added:

```1c
Процедура ПриОткрытии()

    КнопкаВыполнитьНажатие(Неопределено);

КонецПроцедуры
```

Important discovery:

Merely adding `Процедура ПриОткрытии()` was NOT enough.

The event had to be explicitly bound in Configurator:

```text
Form
→ Properties
→ Events
→ ПриОткрытии
→ handler = ПриОткрытии
```

After that:
- opening EPF automatically executed export;
- no manual button press required.

---

# 26. 1C COMMAND-LINE LAUNCH

A direct 1C command-line launch was tested successfully.

Pattern:

```powershell
& "C:\Program Files (x86)\1cv8\8.3.16.1148\bin\1cv8.exe" `
ENTERPRISE `
/S"ONEC-6\U036-alfa" `
/N"Пан Станислав Вячеславович" `
/P"<1C_PASSWORD>" `
/Execute "D:\Users\U036009\TestExportOrders.epf"
```

Behavior:
- 1C starts
- authentication succeeds
- EPF opens
- EPF auto-runs because `ПриОткрытии` is wired
- export executes

---

# 27. POWERSHELL SCRIPT FOR 1C

File created:

```text
D:\Users\U036009\RunAlphaExport.ps1
```

There was an encoding problem with Cyrillic username in BAT/PS1.

Symptoms:
- mojibake in 1C user field
- auto-login failed

Working solution:
Build 1C username from Unicode codepoints.

Known working pattern:

```powershell
$user1C = [string]::Concat(
    [char]1055,[char]1072,[char]1085,[char]32,
    [char]1057,[char]1090,[char]1072,[char]1085,[char]1080,[char]1089,[char]1083,[char]1072,[char]1074,[char]32,
    [char]1042,[char]1103,[char]1095,[char]1077,[char]1089,[char]1083,[char]1072,[char]1074,[char]1086,[char]1074,[char]1080,[char]1095
)

$exe = "C:\Program Files (x86)\1cv8\8.3.16.1148\bin\1cv8.exe"

& $exe ENTERPRISE /S"ONEC-6\U036-alfa" /N"$user1C" /P"<1C_PASSWORD>" /Execute "D:\Users\U036009\TestExportOrders.epf"
```

This worked.

Do not commit real password.

---

# 28. AUTOMATIC CLOSING OF 1C

To avoid accumulating 1C windows/sessions, the EPF was modified to end with:

```1c
ЗавершитьРаботуСистемы();
```

Test result:
- 1C starts
- export runs
- output is produced
- 1C closes itself

This worked for the CSV prototype.

For interactive HTTPS test, automatic close was temporarily removed so that response text could be inspected.

---

# 29. WINDOWS TASK SCHEDULER EXPERIMENT

Windows Task Scheduler job was created.

Action:

```text
powershell.exe
```

Arguments:

```text
-NoProfile -ExecutionPolicy Bypass -File "D:\Users\U036009\RunAlphaExport.ps1"
```

Working directory:

```text
D:\Users\U036009
```

Task setting:

```text
If task is already running -> Do not start a new instance
```

Timeout was discussed around 30 minutes.

## Important unresolved issue

Desired mode:

```text
Run whether user is logged on or not
```

did NOT actually work.

Windows reported requirement for:

```text
Log on as a batch job
```

for:

```text
5S\U036009
```

Local Security Policy:

```text
secpol.msc
```

could be opened, but permissions did not allow granting this right.

Observed behavior:
- task saved;
- non-interactive run did not start;
- "Run only when user is logged on" immediately worked.

Therefore:

### Fully unattended scheduling is NOT solved.

Future options:

1. ask 5Systems to grant `Log on as a batch job`;
2. ask for a dedicated service account with this right;
3. use 1C scheduled jobs/server-side execution;
4. temporary workaround: keep Windows user session logged in.

Do not consider option 4 production-grade.

---

# 30. FTP / BEGET HISTORY — ABANDONED

Earlier architecture tried to send exported CSV via FTP.

Beget server:

```text
e962999k.beget.tech
```

Network test:

```powershell
Test-NetConnection e962999k.beget.tech -Port 21
```

Result:

```text
TcpTestSucceeded : True
```

A dedicated FTP user was created:

```text
e962999k_1c
```

Configured folder:

```text
/e962999k.beget.tech/public_html/1C_reports
```

Plain FTP login failed.

Using curl showed exact reason:

```text
530 Non-anonymous sessions must use encryption.
```

Thus FTPS required.

FTPS using Windows curl / Schannel then failed during TLS renegotiation:

```text
SEC_E_INVALID_TOKEN (0x80090308)
```

Conclusion:
FTP/FTPS via Beget was abandoned.

Do not reintroduce it unless there is a compelling new reason.

---

# 31. HTTPS CONNECTIVITY TEST FROM 5SYSTEMS

A harmless test file was created:

```text
C:\Temp\https_test.txt
```

PowerShell/curl test:

```powershell
curl.exe -X POST -F "file=@C:\Temp\https_test.txt" https://httpbin.org/post
```

Result:
- outbound HTTPS works;
- external Internet over 443 works;
- httpbin returned uploaded content.

This proved 5Systems environment can push data outward over HTTPS.

---

# 32. DIRECT JSON FROM 1C — PROVEN

This is one of the most important milestones.

`TestExportOrders.epf` was modified to:

1. run the WorkOrder query;
2. build an array of structures;
3. serialize JSON;
4. open HTTPS connection;
5. POST JSON directly from 1C;
6. read response.

Test endpoint:

```text
https://httpbin.org/post
```

Observed result:

```text
JSON сформирован.
Размер JSON: 1 851 символов
HTTP status: 200
```

The returned response contained the real JSON payload.

Therefore this chain is proven:

```text
Alpha-Auto
→ 1C query
→ JSON
→ HTTPS POST
→ external endpoint
```

on 1C platform:

```text
8.3.16.1148
```

---

# 33. WORKING 1C JSON SERIALIZATION PATTERN

Known working:

```1c
ЗаписьJSON = Новый ЗаписьJSON;

ЗаписьJSON.УстановитьСтроку();

ЗаписатьJSON(
    ЗаписьJSON,
    Данные
);

ТелоJSON = ЗаписьJSON.Закрыть();
```

The JSON test included fields:

- source
- orders[]
- number
- date
- customer
- car
- amount

---

# 34. WORKING 1C HTTPS PATTERN

Known working code pattern:

```1c
ЗащищенноеСоединение =
    Новый ЗащищенноеСоединениеOpenSSL;

Соединение =
    Новый HTTPСоединение(
        "httpbin.org",
        443,
        ,
        ,
        ,
        ,
        ЗащищенноеСоединение
    );

HTTPЗапрос = Новый HTTPЗапрос("/post");

HTTPЗапрос.Заголовки.Вставить(
    "Content-Type",
    "application/json; charset=utf-8"
);

HTTPЗапрос.Заголовки.Вставить(
    "Accept",
    "application/json"
);

HTTPЗапрос.УстановитьТелоИзСтроки(
    ТелоJSON,
    КодировкаТекста.UTF8
);

HTTPОтвет =
    Соединение.ОтправитьДляОбработки(HTTPЗапрос);

КодОтвета = HTTPОтвет.КодСостояния;

ТекстОтвета =
    HTTPОтвет.ПолучитьТелоКакСтроку();
```

This is confirmed working.

Next real version must add:

```text
Authorization: Bearer <API_TOKEN>
```

and target our own backend.

---

# 35. REAL DATA OBSERVED IN JSON TEST

Real Alpha-Auto values observed included:

Work Order numbers such as:

```text
ПС00010196
```

Dates such as:

```text
2026-09-12T18:38:09
```

Customer names.

Vehicle descriptions including:
- make/model;
- registration number;
- VIN.

Amounts observed included examples like:
- 18500
- 1300
- 404600
- 34180

JSON response escaped Cyrillic using:

```text
\u....
```

This is normal JSON Unicode escaping and not a data problem.

---

# 36. SECURITY NOTE ABOUT HTTPBIN

Real customer data (names/VIN/amounts) was sent once to httpbin during technical testing.

Do NOT send real customer data to httpbin again.

Future real payloads must go only to our controlled API.

---

# 37. TARGET 1C PAYLOAD CONTRACT

The previous httpbin test used roughly:

```json
{
  "source": "alpha-auto",
  "orders": [...]
}
```

The next real implementation must use backend contract:

```json
{
  "source": "alpha-auto",
  "branch": "kahovka",
  "entity": "work_orders",
  "exported_at": "2026-09-13T10:00:00",
  "batch_id": "20260913-100000",
  "records": [
    {
      "number": "...",
      "date": "...",
      "customer": "...",
      "car": "...",
      "amount": 18500
    }
  ]
}
```

Header:

```text
Authorization: Bearer <API_TOKEN>
```

---

# 38. LOCAL TUNNEL EXPERIMENTS — ABANDONED

Goal:
Temporarily expose local FastAPI to 1C before cloud deployment.

## Cloudflare Quick Tunnel

Installed:

```text
cloudflared 2026.9.1
```

Local backend health worked.

Tunnel URLs intermittently worked but repeatedly failed with:

- Cloudflare 1033
- 502 Bad Gateway
- QUIC timeout

Tried:
- localhost
- 127.0.0.1
- QUIC
- HTTP/2

Unreliable.

Abandoned.

## ngrok

Installed:
initially 3.3.1 via winget

Account required >= 3.20.0

Updated successfully to:

```text
3.39.11
```

Authtoken configured.

But tunnel remained:

```text
reconnecting
```

with error:

```text
failed to send authentication request: failed to fetch CRL
```

Changing network did not solve it.

Abandoned.

Conclusion:
Do not waste more time on dev tunnels.
Deploy backend to real cloud staging.

---

# 39. WHY WE MOVED TO RAILWAY

The goal is now:

```text
Alpha-Auto
→ 1C
→ JSON
→ HTTPS
→ Railway FastAPI
→ Railway PostgreSQL
```

This is much closer to production architecture than temporary tunnels.

Current immediate milestone:

### Real Alpha-Auto → 1C JSON → Railway FastAPI → Railway PostgreSQL

This is the next major proof point.

---

# 40. DATA MODEL EXPLORATION AFTER E2E

After real E2E succeeds, next priority is NOT pretty UI.

Next priority is investigating Alpha-Auto schema and identifying real objects/fields for:

- stable WorkOrder identifier / GUID / reference
- status
- branch
- workshop
- vehicle ID
- VIN
- registration number
- insurance company
- service advisor/master
- repair employees
- labor operations
- labor hours
- labor sales price
- parts
- part cost
- part sales price
- paint/materials
- payment state
- open/closed status
- source timestamps
- operational workflow stage
- status-change timestamps
- any source last-modified field

Model the product from actual Alpha-Auto facts, not assumptions.

---

# 41. FILE / PATH REFERENCE

## RDP

Server:

```text
dc1.5systems.ru:16139
```

User:

```text
5S\U036009
```

Working RDP file:

```text
Alpha_Auto_1C.rdp
```

## 1C

Executable:

```text
C:\Program Files (x86)\1cv8\8.3.16.1148\bin\1cv8.exe
```

Server/base:

```text
ONEC-6\U036-alfa
```

1C user:

```text
Пан Станислав Вячеславович
```

External processing:

```text
D:\Users\U036009\TestExportOrders.epf
```

Runner script:

```text
D:\Users\U036009\RunAlphaExport.ps1
```

CSV prototype:

```text
C:\Temp\TestExportOrders.csv
```

## GitHub

```text
https://github.com/piloterist/AutoServiceAISolution.git
```

## Current commit

```text
9e8132397c28ed3c6bb729bcbe4cbab105fab25d
```

---

# 42. SECRETS INTENTIONALLY OMITTED

Known to exist but NOT included:

- RDP password
- 1C password
- local `.env`
- local dev API token
- future Railway production API token
- PostgreSQL password
- ngrok auth token
- Beget/FTP password

Never commit these.

Use:
- env vars
- secret stores
- Railway variables
- secure local storage

---

# 43. CURRENT PROOF POINTS

## Proven

1. RDP access works.
2. Full desktop access works.
3. 1C Configurator access works.
4. Alpha-Auto WorkOrder query works.
5. 10 WorkOrders can be read.
6. CSV can be created.
7. EPF can auto-run on open.
8. 1C can be launched from PowerShell.
9. 1C can authenticate automatically.
10. 1C can close itself after export.
11. Task Scheduler can run chain while user is logged in.
12. Outbound HTTPS from 5Systems works.
13. 1C 8.3.16 can serialize JSON.
14. 1C can POST JSON via HTTPS.
15. Local FastAPI import works.
16. Local PostgreSQL works.
17. Auth works.
18. UPSERT works.
19. Import audit works.
20. Git/GitHub works.
21. Railway PostgreSQL exists.

## Not yet solved

1. true unattended Windows Task Scheduler execution without logged-in user;
2. `Log on as a batch job` permission;
3. production scheduling strategy;
4. stable Alpha-Auto source key/GUID;
5. complete source data model;
6. Railway backend deployment;
7. real 1C -> Railway API test;
8. frontend product UI;
9. user/role auth;
10. production monitoring/backups;
11. provisioning automation for new customers;
12. subscription/licensing mechanics.

---

# 44. IMMEDIATE NEXT ACTIONS

Claude Code should continue from here:

## Step A — Railway backend deployment

Create backend service from:

```text
piloterist/AutoServiceAISolution
```

Configure:

```text
Root Directory = backend
Dockerfile = Dockerfile
Start Command = blank
Healthcheck = /health
```

Variables:

```text
DATABASE_URL=postgresql+psycopg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}
ENVIRONMENT=production
LOG_LEVEL=INFO
API_TOKEN=<new production/staging secret>
```

Deploy.

Verify:
- build succeeds;
- preDeploy Alembic succeeds;
- public HTTPS URL available;
- `/health` returns 200;
- tables exist.

## Step B — 1C real integration

Modify `TestExportOrders.epf` so it sends the 10 real WorkOrders to Railway endpoint:

```text
POST https://<railway-domain>/api/v1/import/work-orders
```

with:

```text
Authorization: Bearer <same token>
```

Then verify:
- response 200;
- ImportBatch created;
- 10 WorkOrder rows inserted;
- repeat import does not duplicate;
- changed amount updates existing row.

## Step C — only after real E2E

Investigate Alpha-Auto metadata and expand data model.

Do NOT jump directly to a pretty frontend before this.

---

# 45. WORKING STYLE GUIDANCE FOR CLAUDE CODE

- Use the existing repository as truth.
- Prefer small reversible steps.
- Run tests after changes.
- Do not add speculative architecture.
- Preserve provider independence.
- Preserve tenant-per-instance design.
- Do not introduce multi-tenancy unless explicitly requested.
- Do not hardcode customer-specific workflows/KPIs.
- Do not put secrets in source.
- For 1C, give complete code replacements when possible.
- For infrastructure, explain exactly what is being changed.
- If browser automation is available, use it for Railway/GitHub setup when appropriate.
- If Chrome/Browser tooling is connected, it may be used to inspect Railway UI, GitHub, logs, deployment state, and API docs, but never expose secrets in screenshots/log output.
- Keep focus on the next milestone: real Alpha-Auto -> Railway FastAPI -> Railway PostgreSQL.

---

# 46. NOTE ABOUT CHROME / BROWSER TOOLING

The user is intentionally moving the workflow to Claude Code because they want tighter integration with:
- VS Code / Claude Code
- terminal
- repository
- browser / Chrome tooling where available

Expected working mode:
- code changes directly in repo;
- terminal commands executed directly;
- browser used for Railway/GitHub deployment steps when available;
- less manual copy/paste between assistants.

This handoff should be placed in the repository root as `CLAUDE.md` so Claude Code automatically has persistent project context.
