"""Audit trail for Planner schedule records (see product brief part 6): who
created/changed/deleted a record and what changed, viewable from Settings.

Scoped deliberately narrow - only fields a person can actually type/pick in
the Planner (post, time, status, the ЗН it's linked to, ...) ever appear in
`changes`. Anything that only ever arrives from the 1C import (amount, VIN,
customer, ...) is never logged here - it already has its own audit trail on
the 1C side, and duplicating it would blur "who changed this deliberately"
with "1C re-sent a field". Entity rows themselves (see the future Planner
models) carry their own created_by/updated_by columns for the common case
of "who last touched this row"; this table exists for the history, which a
plain column can't hold.

Empty until the Planner's own write endpoints exist and call
services/audit_log_service.py - the table/endpoint are scaffolded now so
Settings has somewhere to point a "Логи" tab at.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_DELETE = "delete"
ACTIONS = (ACTION_CREATE, ACTION_UPDATE, ACTION_DELETE)


class ScheduleAuditLog(Base):
    __tablename__ = "schedule_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # What kind of Planner record this is about (e.g. "workshop_job",
    # "body_car") and its id - not a real foreign key, since the target row
    # may since have been deleted (that's exactly the case ACTION_DELETE
    # needs to keep logging).
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False)

    # {"field_name": {"old": ..., "new": ...}} - only manually-entered
    # fields, see module docstring. Empty/omitted fields on ACTION_CREATE
    # ("old" is always null) and ACTION_DELETE (a snapshot, "new" is null).
    changes: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # SET NULL, not CASCADE: deleting a user must not erase the history of
    # what they did - `actor_name` keeps the log readable even then.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ScheduleAuditLog {self.action} {self.entity_type}:{self.entity_id}>"
