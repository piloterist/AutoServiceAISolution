# Architecture

## Product model

This is a **tenant-per-instance hosted SaaS**, not a multi-tenant single
database. One codebase/image set is deployed once per client:

```
Client A                         Client B
 - frontend container             - frontend container
 - backend container              - backend container
 - own PostgreSQL database        - own PostgreSQL database
 - own env vars / config          - own env vars / config
```

There is therefore **no `tenant_id`/`client_id` column anywhere** - isolation
is at the infrastructure level (separate DB, separate containers), not at the
row level. Client-specific behavior must never be expressed as `if client ==
"pan-motors"` in application code; it is expressed as configuration data or
environment variables that differ between deployments of the same code.

## Style: modular monolith

One deployable backend, organized into modules by responsibility
(`core`, `db`, `models`, `schemas`, `api`, `services`), not microservices.
No message broker, no cache, no CQRS/event sourcing - none of that is needed
at this stage and each would add operational cost without a corresponding
requirement today.

## Aggregate root: Work Order

`WorkOrder` (`backend/app/models/work_order.py`) is the entity everything
else attaches to - revenue, cost, labor, parts, staffing, margin, status,
deadlines, reporting. `Vehicle` is not an aggregate root; a vehicle belongs to
a work order, not the other way round. Future models (parts, labor lines,
staff assignments, status history) should reference `WorkOrder.id`.

## What is intentionally NOT built yet

The following are named in the product vision but must stay data/config,
never hardcoded, and are deliberately **not implemented** in this skeleton
so no premature, possibly-wrong shape gets baked in:

- `WorkflowDefinition` / `WorkflowStage` - per-client Kanban stages and
  work order status flow.
- `MetricDefinition` - per-client KPI/efficiency formulas.
- `FeatureFlag` - which optional modules are enabled for a given instance.
- `ClientConfiguration` - department names, business roles, other per-client
  labels/settings.

When these are built, they belong in their own modules (e.g.
`app/models/workflow.py`, `app/services/workflow_engine.py`) and should be
driven by rows in the database (or env-supplied config), never by Python
`if`/`match` branches naming a specific client. The current code has no
hardcoded Kanban stages, statuses, department names, KPIs, or Pan Motors
specifics - grep for `pan` / `motors` / `kahovka` in `backend/app` and
`frontend/app` finds nothing but comments/test fixtures using it as sample
data.

## Identity / upsert strategy

`WorkOrder` is deduplicated on `(source_system, external_number)` today via a
unique constraint and a real `INSERT ... ON CONFLICT DO UPDATE`. A nullable
`source_key` column already exists so a future migration can switch the
natural key to a more reliable identifier from the source system without a
breaking schema change - only the conflict target and upsert logic in
`app/services/import_service.py` would need to move to `source_key`.

## Data flow: 1C -> platform

1C/Alpha-Auto already serializes exports to JSON and POSTs them over HTTPS.
The corresponding inbound contract is `POST /api/v1/import/work-orders`
(`backend/app/api/v1/endpoints/import_work_orders.py`), authenticated by a
per-instance bearer token (`API_TOKEN`). Every request - success or failure -
is recorded as an `ImportBatch` row for full traceability, independent of
whether the individual `WorkOrder` upserts succeeded.

## Money

`WorkOrder.amount` is `NUMERIC(14,2)` (Python `Decimal`), never `float`, to
avoid rounding errors in financial data.

## Backend request handling

Routes are synchronous (`def`, not `async def`) and use a plain SQLAlchemy
`Session`. FastAPI runs sync path operations in a thread pool automatically,
so this avoids the added complexity of async SQLAlchemy/async drivers while
the write volume from a single 1C export job is low. This can be revisited
if/when throughput requires it.
