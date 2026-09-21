"""Writes to schedule_audit_log - see models/schedule_audit_log.py for what
belongs here and why. Called from services/planner_service.py after every
create/update/delete of a Planner record.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.schedule_audit_log import ScheduleAuditLog


def record_change(
    db: Session,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    changes: dict,
    actor_user_id: uuid.UUID | None,
    actor_name: str,
) -> None:
    """Only called with a non-empty `changes` on update (no-op edits don't
    log); create/delete always log (changes is the created/deleted snapshot
    in that case) - callers decide, this just writes the row."""
    db.add(
        ScheduleAuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            changes=changes,
            actor_user_id=actor_user_id,
            actor_name=actor_name,
        )
    )
