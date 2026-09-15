"""Append-only timeline of a Work Order's status transitions.

Populated during import (see services/import_service.py), not written to
directly anywhere else: whenever a record's incoming status differs from
whatever segment is currently open for that work order, the open segment is
closed (`last_seen_at` set) and a new one is opened (`last_seen_at` left
NULL). An unchanged status on a later import does nothing - the existing
open segment already covers it.

Example: first seen "В работе" on 10.09 -> one open row. Same status again
on 11.09 -> no new row (nothing changed). "Ожидание запчастей" on 12.09 ->
the "В работе" row is closed at 12.09, and a new open row starts there.

This is what lets the work order detail page show "spent 2 days in В
работе, 6 hours in Ожидание запчастей, ...".
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkOrderStatusHistory(Base):
    __tablename__ = "work_order_status_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Plain text, whatever the source sends - same reasoning as
    # WorkOrder.status (client-specific values, never hardcoded here).
    status: Mapped[str] = mapped_column(String(100), nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # NULL = this is the currently-open segment (the work order's status as
    # of the most recent import). Indexed since _record_status_history
    # looks this up by work_order_id + "is the open segment" on every
    # import.
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WorkOrderStatusHistory {self.work_order_id} {self.status!r}>"
