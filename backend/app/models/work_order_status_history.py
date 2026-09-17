"""Real status change history, sourced from 1C's own object version log
(РегистрСведений.пп_ВерсииОбъектов), not built by this application.

Replaces the earlier mechanism, which inferred status changes by diffing
consecutive imports (comparing the incoming status against whatever the
work order's status was before the previous import) and timestamped them
with this backend's own clock. That approach could only ever be as precise
as how often imports happened to run, and had no notion of *who* changed
the status. 1C's version history gives the real moment (ДатаВерсии) and
the real author (АвторВерсии) directly - see 1c/TestExportOrders.bsl for
how it's read (strictly read-only against 1C) and
services/import_service.py for how it's turned into rows here.

One row per real status CHANGE, not per object version - a new
пп_ВерсииОбъектов version can exist because any requisite changed (amount,
labor lines, comment, ...), not just Состояние, so consecutive versions
that resolve to the same status collapse into a single row (see
_record_status_history in import_service.py). `version_number` is the
1C НомерВерсии of the version where this status first appeared - the
natural idempotency key together with work_order_id, since a full
re-export re-sends the whole available version history every time.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkOrderStatusHistory(Base):
    __tablename__ = "work_order_status_history"
    __table_args__ = (
        UniqueConstraint(
            "work_order_id", "version_number", name="uq_work_order_status_history_version"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 1C РегистрСведений.пп_ВерсииОбъектов.НомерВерсии.
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # 1C ДатаВерсии - the real moment this status became effective. Never
    # an import/observation/export timestamp.
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    # 1C АвторВерсии, as plain text (whatever 1C sends) - nullable since a
    # version can in principle come back without one.
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Plain text, whatever the source sends - same reasoning as
    # WorkOrder.status (client-specific values, never hardcoded here).
    status: Mapped[str] = mapped_column(String(100), nullable=False)
    # UUID (as text) of Справочник.ВидыСостоянийЗаказНарядов that `status`
    # was resolved from - a technical/traceability field, not shown in the
    # UI (see StatusHistoryItem).
    status_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<WorkOrderStatusHistory {self.work_order_id} v{self.version_number} {self.status!r}>"
        )
