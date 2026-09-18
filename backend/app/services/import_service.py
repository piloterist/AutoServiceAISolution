"""Business logic for importing Work Orders from an external source (1C/Alpha-Auto).

Kept deliberately simple: one upsert per record inside a single DB
transaction, plus an ImportBatch row for traceability. No rule engine, no
per-client branching - that belongs to future configuration-driven layers
(see ARCHITECTURE.md), not here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.import_batch import ImportBatch
from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLaborLine, WorkOrderPartLine
from app.models.work_order_payment_event import WorkOrderPaymentEvent
from app.models.work_order_payment_history import WorkOrderPaymentHistory
from app.models.work_order_status_history import WorkOrderStatusHistory
from app.schemas.import_work_order import (
    ImportPaymentEventRecord,
    ImportStatusHistoryRecord,
    ImportWorkOrderRecord,
    ImportWorkOrdersRequest,
)
from app.services.internal_order_rules import (
    internal_order_allowed,
    is_external_repair_type,
    normalize_vin,
)

logger = structlog.get_logger(__name__)


class ImportProcessingError(Exception):
    """Raised when a batch could not be persisted at all."""


def _upsert_work_order(
    db: Session, source: str, exported_at, record: ImportWorkOrderRecord
) -> tuple[uuid.UUID, bool]:
    """Insert or update a single WorkOrder by (source_system, external_number).

    Returns (work_order_id, inserted) - inserted is True if a new row was
    created, False if an existing row was updated. Uses a real Postgres
    UPSERT (INSERT ... ON CONFLICT DO UPDATE) so this is safe under
    concurrent/repeated delivery of the same document.
    """
    values = {
        "external_number": record.number,
        "source_system": source,
        "source_key": record.source_key,
        "document_date": record.date,
        "created_date": record.created_date,
        "start_date": record.start_date,
        "end_date": record.end_date,
        "closed_date": record.closed_date,
        "customer_name": record.customer,
        "payer_name": record.payer,
        "vehicle_description": record.car,
        "status": record.status,
        "department": record.department,
        "repair_type": record.repair_type,
        "organization": record.organization,
        "vin": record.vin,
        "car_key": normalize_vin(record.vin),
        "amount": record.amount,
        "deal_amount": record.deal_amount,
        "debt_amount": record.debt_amount,
        "paid_amount": record.paid_amount,
        "payment_percent": record.payment_percent,
        "source_updated_at": exported_at,
        "raw_payload": record.model_dump(mode="json"),
    }

    update_columns = {
        key: value
        for key, value in values.items()
        if key not in ("external_number", "source_system")
    }
    # `onupdate=func.now()` on the ORM column only fires for ORM-driven
    # UPDATEs; a raw ON CONFLICT DO UPDATE bypasses that, so bump it here.
    update_columns["updated_at"] = func.now()

    # Use the plain Core Table (not the ORM-mapped class) for this statement:
    # pg_insert() on an ORM entity triggers SQLAlchemy's "ORM-enabled INSERT"
    # path, which only understands RETURNING of mapped columns and silently
    # drops extra expressions like our `xmax = 0` marker. The Core table
    # gives us a plain RETURNING clause instead.
    table = WorkOrder.__table__
    stmt = pg_insert(table).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[table.c.source_system, table.c.external_number],
        set_=update_columns,
    ).returning(table.c.id, text("(xmax = 0) AS inserted"))

    row = db.execute(stmt).mappings().first()
    return row["id"], bool(row["inserted"])


def _record_status_history(
    db: Session,
    work_order_id: uuid.UUID,
    versions: list[ImportStatusHistoryRecord],
) -> None:
    """Real status history from 1C's own РегистрСведений.пп_ВерсииОбъектов
    version log (see 1c/TestExportOrders.bsl) - replaces the old mechanism
    that inferred status changes by diffing consecutive imports.

    `versions` is every available object version for this work order,
    unfiltered and in whatever order 1C sent them: a version can exist
    because ANY requisite changed, not just Состояние, so this sorts by
    version_number and collapses consecutive versions that resolve to the
    same status into a single row - the first version, or the first
    version *after* a genuine change, only. A version with no resolvable
    status (see ImportStatusHistoryRecord) is skipped entirely, not
    treated as "no status" - it neither closes nor opens anything, the
    comparison just carries on to the next version as if it wasn't there.

    Idempotent: an INSERT ... ON CONFLICT (work_order_id, version_number)
    DO UPDATE, since a full re-export re-sends the whole available version
    history every time - existing rows get refreshed in place (harmless if
    unchanged), new ones get added, nothing is duplicated.

    Also reconciles *stale* rows within this payload's own version_number
    range: if an earlier import saw versions {1, 3} (version 2 missing -
    e.g. a transient read error) and stored a row for 3 (looked like a
    real transition at the time), then a later import that fills the gap
    and sees {1, 2, 3} where 2 and 3 share a status must end up with just
    {1, 2} - the stale row for 3 has to go. Only rows *inside* the
    min..max version_number this payload actually covers are eligible for
    deletion, and only when this payload resolved at least one real
    status (an empty `rows` - e.g. every version in range failed to read
    this time - leaves existing rows alone rather than risk deleting good
    data over a transient failure); versions outside that range (earlier
    or later history this payload doesn't know about) are never touched,
    which is what keeps a partial/incremental payload safe.
    """
    if not versions:
        return

    ordered = sorted(versions, key=lambda v: v.version_number)

    rows = []
    previous_status: str | None = None
    for version in ordered:
        if not version.status:
            continue
        if version.status == previous_status:
            continue
        previous_status = version.status
        rows.append(
            {
                "id": uuid.uuid4(),
                "work_order_id": work_order_id,
                "version_number": version.version_number,
                "changed_at": version.changed_at,
                "author": version.author,
                "status": version.status,
                "status_uuid": version.status_uuid,
            }
        )

    if not rows:
        return

    kept_version_numbers = [row["version_number"] for row in rows]
    db.execute(
        delete(WorkOrderStatusHistory).where(
            WorkOrderStatusHistory.work_order_id == work_order_id,
            WorkOrderStatusHistory.version_number >= ordered[0].version_number,
            WorkOrderStatusHistory.version_number <= ordered[-1].version_number,
            WorkOrderStatusHistory.version_number.not_in(kept_version_numbers),
        )
    )

    table = WorkOrderStatusHistory.__table__
    stmt = pg_insert(table).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[table.c.work_order_id, table.c.version_number],
        set_={
            "changed_at": stmt.excluded.changed_at,
            "author": stmt.excluded.author,
            "status": stmt.excluded.status,
            "status_uuid": stmt.excluded.status_uuid,
        },
    )
    db.execute(stmt)


def _record_payment_history(
    db: Session,
    work_order_id: uuid.UUID,
    deal_amount: Decimal | None,
    debt_amount: Decimal | None,
    paid_amount: Decimal | None,
    payment_percent: Decimal | None,
    observed_at: datetime,
) -> None:
    """Append-only payment snapshot - see
    models/work_order_payment_history.py.

    No-ops when there's nothing to track: the export sent no payment data
    at all for this record, or all four values are unchanged from the most
    recent snapshot (an unchanged payment state on a later import doesn't
    add a row, same reasoning as `_record_status_history`).
    """
    if (
        deal_amount is None
        and debt_amount is None
        and paid_amount is None
        and payment_percent is None
    ):
        return

    last = db.execute(
        select(WorkOrderPaymentHistory)
        .where(WorkOrderPaymentHistory.work_order_id == work_order_id)
        .order_by(WorkOrderPaymentHistory.observed_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if (
        last is not None
        and last.deal_amount == deal_amount
        and last.debt_amount == debt_amount
        and last.paid_amount == paid_amount
        and last.payment_percent == payment_percent
    ):
        return

    db.add(
        WorkOrderPaymentHistory(
            work_order_id=work_order_id,
            observed_at=observed_at,
            deal_amount=deal_amount,
            debt_amount=debt_amount,
            paid_amount=paid_amount,
            payment_percent=payment_percent,
        )
    )


def _record_payment_events(
    db: Session,
    work_order_id: uuid.UUID,
    events: list[ImportPaymentEventRecord],
) -> None:
    """Idempotently insert real dated payment movements - see
    models/work_order_payment_event.py.

    A bulk INSERT ... ON CONFLICT DO NOTHING rather than a per-event
    existence check: a full historical re-export re-sends every payment
    for every work order every time (that's how the historical backfill
    works - see the payments batch query in 1c/TestExportOrders.bsl), so
    this needs to stay cheap at a few thousand rows per batch, not do one
    SELECT per event.
    """
    if not events:
        return

    rows = [
        {
            "id": uuid.uuid4(),
            "work_order_id": work_order_id,
            "paid_at": event.paid_at,
            "amount": event.amount,
            "source_document_id": event.source_document_id,
            "source_document_type": event.source_document_type,
            "source_document_number": event.source_document_number,
            "line_number": event.line_number,
        }
        for event in events
    ]

    table = WorkOrderPaymentEvent.__table__
    stmt = pg_insert(table).values(rows)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=[table.c.work_order_id, table.c.source_document_id, table.c.line_number]
    )
    db.execute(stmt)


def _replace_line_items(
    db: Session, work_order_id: uuid.UUID, record: ImportWorkOrderRecord
) -> None:
    """Replace a work order's labor/parts lines wholesale with what the
    source just sent - 1C is the source of truth for a work order's current
    lines, not something we merge/diff incrementally.
    """
    db.execute(delete(WorkOrderLaborLine).where(WorkOrderLaborLine.work_order_id == work_order_id))
    db.execute(delete(WorkOrderPartLine).where(WorkOrderPartLine.work_order_id == work_order_id))

    for line in record.labor:
        db.add(
            WorkOrderLaborLine(
                work_order_id=work_order_id,
                operation_name=line.operation,
                price=line.price,
                amount=line.amount,
            )
        )

    for line in record.parts:
        db.add(
            WorkOrderPartLine(
                work_order_id=work_order_id,
                item_name=line.item,
                quantity=line.quantity,
                price=line.price,
                amount=line.amount,
            )
        )


def _recompute_internal_flags(db: Session, car_keys: set[str | None]) -> None:
    """Recomputes WorkOrder.is_internal for every work order sharing a
    car_key with this import - see services/internal_order_rules.py for the
    actual rules ("внутренний" = same car as an external/страховой sibling,
    plus the organization/payer rule).

    Scoped to `car_keys` (this payload's own VINs), not the whole table: a
    work order's classification can only change if one of ITS car_key
    siblings changed in this import (a new external sibling appeared, an
    existing one's repair_type/org/payer changed) - nothing about any other
    car_key's grouping was touched, so recomputing the whole table on every
    import would be pure waste at scale. None/empty car_keys are dropped -
    a work order with no valid VIN can't be grouped with anything (see
    internal_order_rules module docstring) and is simply never internal.
    """
    keys = {key for key in car_keys if key}
    if not keys:
        return

    table = WorkOrder.__table__
    rows = db.execute(
        select(
            table.c.id,
            table.c.car_key,
            table.c.repair_type,
            table.c.organization,
            table.c.payer_name,
        ).where(table.c.car_key.in_(keys))
    ).all()

    by_car_key: dict[str, list] = {}
    for row in rows:
        by_car_key.setdefault(row.car_key, []).append(row)

    internal_ids: list[uuid.UUID] = []
    non_internal_ids: list[uuid.UUID] = []

    for group in by_car_key.values():
        has_external_sibling = any(is_external_repair_type(row.repair_type) for row in group)
        for row in group:
            is_internal = (
                has_external_sibling
                and not is_external_repair_type(row.repair_type)
                and internal_order_allowed(row.organization, row.payer_name)
            )
            (internal_ids if is_internal else non_internal_ids).append(row.id)

    if internal_ids:
        db.execute(update(table).where(table.c.id.in_(internal_ids)).values(is_internal=True))
    if non_internal_ids:
        db.execute(update(table).where(table.c.id.in_(non_internal_ids)).values(is_internal=False))


# A single multi-thousand-record transaction held the whole batch's ORM
# objects (labor/part lines, payment-history snapshots) pending in memory,
# unflushed, until one `db.flush()` at the very end - fine at a few thousand
# records, but it stopped scaling once real exports grew large: an 8,000-record
# import degraded badly enough to make the whole backend unresponsive
# (2026-09-17 incident). Chunking bounds memory to one chunk's worth of
# pending objects at a time and commits/releases locks between chunks instead
# of holding them for the whole import's duration.
CHUNK_SIZE = 200


def process_work_order_import(db: Session, payload: ImportWorkOrdersRequest) -> ImportBatch:
    """Persist an import batch and upsert all of its work order records.

    Processed in chunks of CHUNK_SIZE records, each its own committed
    transaction, rather than one transaction for the whole payload (see
    CHUNK_SIZE above). Every table this touches is upserted idempotently
    (_upsert_work_order, _record_status_history, _record_payment_events), so
    a chunk that commits is safe to see again on a retry - a later chunk
    failing never needs to roll back an earlier chunk's already-committed,
    correct data. A failing chunk is rolled back and logged, and processing
    continues with the next chunk rather than aborting the rest of the
    import - the same "one bad piece doesn't abort the whole batch"
    philosophy already used for individual 1C object versions (see
    1c/TestExportOrders.bsl).

    The ImportBatch row is created up front with status "processing" and its
    counts are updated after every chunk, not just at the end, so a crash or
    a killed request mid-import still leaves an accurate, queryable record of
    how far it got instead of no record at all.
    """
    # This backend's own clock, not `payload.exported_at` - the 1C export
    # sends that as a naive local (MSK) timestamp with no timezone info, so
    # storing it as-is mislabels it as UTC. Used for payment_history's
    # "observed at" snapshots only now - status history is timestamped
    # with 1C's own ДатаВерсии instead (see _record_status_history), not
    # this backend's clock.
    observed_at = datetime.now(UTC)

    batch = ImportBatch(
        batch_id=payload.batch_id,
        source=payload.source,
        entity=payload.entity,
        branch=payload.branch,
        exported_at=payload.exported_at,
        records_received=len(payload.records),
        records_inserted=0,
        records_updated=0,
        status="processing",
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    inserted = 0
    updated = 0
    chunk_errors: list[str] = []
    records = payload.records

    for start in range(0, len(records), CHUNK_SIZE):
        chunk = records[start : start + CHUNK_SIZE]
        chunk_inserted = 0
        chunk_updated = 0
        try:
            for record in chunk:
                work_order_id, was_inserted = _upsert_work_order(
                    db, payload.source, payload.exported_at, record
                )
                _replace_line_items(db, work_order_id, record)
                _record_status_history(db, work_order_id, record.status_history)
                _record_payment_history(
                    db,
                    work_order_id,
                    record.deal_amount,
                    record.debt_amount,
                    record.paid_amount,
                    record.payment_percent,
                    observed_at,
                )
                _record_payment_events(db, work_order_id, record.payment_events)
                if was_inserted:
                    chunk_inserted += 1
                else:
                    chunk_updated += 1
            db.commit()
            inserted += chunk_inserted
            updated += chunk_updated
        except Exception as exc:
            db.rollback()
            chunk_errors.append(f"records {start + 1}-{start + len(chunk)}: {exc}")
            logger.error(
                "import_chunk_failed",
                batch_id=payload.batch_id,
                source=payload.source,
                chunk_start=start,
                chunk_size=len(chunk),
                error=str(exc),
            )
        finally:
            db.expire_all()

        batch.records_inserted = inserted
        batch.records_updated = updated
        db.commit()

    # Runs once, after every chunk has committed - a car_key spanning
    # multiple chunks (or matching an existing DB row from an earlier
    # import) needs the *whole* import's effect visible before grouping.
    try:
        car_keys = {normalize_vin(record.vin) for record in records}
        _recompute_internal_flags(db, car_keys)
        db.commit()
    except Exception as exc:
        db.rollback()
        chunk_errors.append(f"is_internal recompute: {exc}")
        logger.error(
            "import_internal_recompute_failed",
            batch_id=payload.batch_id,
            source=payload.source,
            error=str(exc),
        )

    if chunk_errors:
        batch.status = "failed"
        shown = chunk_errors[:10]
        extra = len(chunk_errors) - len(shown)
        batch.error_message = "; ".join(shown) + (f" (+{extra} more chunk errors)" if extra else "")
    else:
        batch.status = "success"
        batch.error_message = None

    db.commit()
    db.refresh(batch)

    if chunk_errors:
        logger.error(
            "import_failed",
            batch_id=payload.batch_id,
            source=payload.source,
            received=batch.records_received,
            inserted=inserted,
            updated=updated,
            failed_chunks=len(chunk_errors),
        )
        raise ImportProcessingError(batch.error_message or "unknown import error")

    logger.info(
        "import_completed",
        batch_id=payload.batch_id,
        source=payload.source,
        received=batch.records_received,
        inserted=inserted,
        updated=updated,
    )
    return batch
