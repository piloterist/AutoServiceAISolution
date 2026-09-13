"""Business logic for importing Work Orders from an external source (1C/Alpha-Auto).

Kept deliberately simple: one upsert per record inside a single DB
transaction, plus an ImportBatch row for traceability. No rule engine, no
per-client branching - that belongs to future configuration-driven layers
(see ARCHITECTURE.md), not here.
"""

from __future__ import annotations

import structlog
from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.import_batch import ImportBatch
from app.models.work_order import WorkOrder
from app.schemas.import_work_order import ImportWorkOrdersRequest

logger = structlog.get_logger(__name__)


class ImportProcessingError(Exception):
    """Raised when a batch could not be persisted at all."""


def _upsert_work_order(db: Session, source: str, exported_at, record) -> bool:
    """Insert or update a single WorkOrder by (source_system, external_number).

    Returns True if a new row was inserted, False if an existing row was updated.
    Uses a real Postgres UPSERT (INSERT ... ON CONFLICT DO UPDATE) so this is
    safe under concurrent/repeated delivery of the same document.
    """
    values = {
        "external_number": record.number,
        "source_system": source,
        "source_key": record.source_key,
        "document_date": record.date,
        "customer_name": record.customer,
        "vehicle_description": record.car,
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
    return bool(row["inserted"])


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
            if _upsert_work_order(db, payload.source, payload.exported_at, record):
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
