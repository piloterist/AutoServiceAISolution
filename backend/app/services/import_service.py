"""Business logic for importing Work Orders from an external source (1C/Alpha-Auto).

Kept deliberately simple: one upsert per record inside a single DB
transaction, plus an ImportBatch row for traceability. No rule engine, no
per-client branching - that belongs to future configuration-driven layers
(see ARCHITECTURE.md), not here.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import delete, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.import_batch import ImportBatch
from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLaborLine, WorkOrderPartLine
from app.schemas.import_work_order import ImportWorkOrderRecord, ImportWorkOrdersRequest

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
        "amount": record.amount,
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

    try:
        for record in payload.records:
            work_order_id, was_inserted = _upsert_work_order(
                db, payload.source, payload.exported_at, record
            )
            _replace_line_items(db, work_order_id, record)
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
