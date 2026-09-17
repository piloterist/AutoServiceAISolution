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
    ImportWorkOrderRecord,
    ImportWorkOrdersRequest,
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


def _lookup_current_status(db: Session, source: str, external_number: str) -> str | None:
    """The work order's status as it stood *before* this import - looked up
    before `_upsert_work_order` overwrites it, since the raw ON CONFLICT
    UPDATE's RETURNING only ever gives the post-update row. None both when
    the work order doesn't exist yet and when it exists but has no status
    set - both cases are "nothing to compare against" for
    `_record_status_history`.
    """
    return db.execute(
        select(WorkOrder.status).where(
            WorkOrder.source_system == source, WorkOrder.external_number == external_number
        )
    ).scalar_one_or_none()


def _record_status_history(
    db: Session,
    work_order_id: uuid.UUID,
    previous_status: str | None,
    new_status: str | None,
    observed_at: datetime,
) -> None:
    """Append-only status timeline - see models/work_order_status_history.py.

    No-ops when there's nothing to track: no incoming status at all, or the
    status didn't actually change (an unchanged status on a later import
    just means the currently-open segment still applies - it does not get a
    new row, only a genuine transition does).
    """
    if not new_status or previous_status == new_status:
        return

    db.execute(
        update(WorkOrderStatusHistory)
        .where(
            WorkOrderStatusHistory.work_order_id == work_order_id,
            WorkOrderStatusHistory.last_seen_at.is_(None),
        )
        .values(last_seen_at=observed_at)
    )
    db.add(
        WorkOrderStatusHistory(
            work_order_id=work_order_id,
            status=new_status,
            first_seen_at=observed_at,
            last_seen_at=None,
        )
    )


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


def process_work_order_import(db: Session, payload: ImportWorkOrdersRequest) -> ImportBatch:
    """Persist an import batch and upsert all of its work order records.

    The whole batch is processed in a single transaction: either every
    record is applied and the batch is marked "success", or nothing is
    applied and the batch is marked "failed" with the error recorded.
    """
    inserted = 0
    updated = 0
    status = "success"
    error_message: str | None = None
    # This backend's own clock, not `payload.exported_at` - the 1C export
    # sends that as a naive local (MSK) timestamp with no timezone info, so
    # storing it as-is mislabels it as UTC and every status-history
    # timestamp reads ~3 hours ahead of the real time. `received_at` on
    # ImportBatch already uses this same "our own clock" convention (see
    # below) - this keeps status history consistent with it. One timestamp
    # for the whole batch, not per-record, so nothing skews within a batch.
    observed_at = datetime.now(UTC)

    try:
        for record in payload.records:
            previous_status = _lookup_current_status(db, payload.source, record.number)
            work_order_id, was_inserted = _upsert_work_order(
                db, payload.source, payload.exported_at, record
            )
            _replace_line_items(db, work_order_id, record)
            _record_status_history(db, work_order_id, previous_status, record.status, observed_at)
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
                inserted += 1
            else:
                updated += 1
        db.flush()
    except Exception as exc:
        db.rollback()
        status = "failed"
        error_message = str(exc)
        inserted = 0
        updated = 0
        logger.error(
            "import_failed", batch_id=payload.batch_id, source=payload.source, error=error_message
        )

    batch = ImportBatch(
        batch_id=payload.batch_id,
        source=payload.source,
        entity=payload.entity,
        branch=payload.branch,
        exported_at=payload.exported_at,
        records_received=len(payload.records),
        records_inserted=inserted,
        records_updated=updated,
        status=status,
        error_message=error_message,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    if status == "failed":
        raise ImportProcessingError(error_message or "unknown import error")

    logger.info(
        "import_completed",
        batch_id=payload.batch_id,
        source=payload.source,
        received=batch.records_received,
        inserted=inserted,
        updated=updated,
    )
    return batch
