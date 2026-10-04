"""Settings -> IP-телефония: "Цех — Телефон — Добавочный" - maps a raw Zeon
`dst` (dialed number or advertising/IVR line name, e.g. "79261537227" or
"pan2") and/or `exten` (добавочный - the internal extension that answered an
inbound call or placed an outbound one) to a Workshop, so every imported
call (see models/call_record.py's workshop_id/workshop_source) can be
attributed to a цех - see services/call_workshop_service.py for the actual
matching algorithm.

Deliberately NOT unique on `phone` or `extension` alone: the matching rule
(see call_workshop_service.determine_workshop) looks up ALL rows matching a
given phone/extension and only assigns a цех when every row found agrees on
the same Workshop - an operator entering the same phone twice under two
different workshops is exactly the ambiguous case that rule is built to
detect and report ("несколько цехов"), not something this table should
silently prevent.

At least one of phone/extension must be set (enforced by a CHECK constraint
and mirrored in schemas/telephony.py) - a row with neither would never
match anything.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkshopPhoneMapping(Base):
    __tablename__ = "workshop_phone_mappings"
    __table_args__ = (
        CheckConstraint(
            "phone IS NOT NULL OR extension IS NOT NULL",
            name="phone_or_extension",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workshop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workshops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Normalized to "7XXXXXXXXXX" for anything that parses as a real phone
    # number; a line/IVR name (e.g. "pan2") is kept as-is, lowercased - see
    # call_workshop_service.normalize_phone_or_line, applied identically
    # here (on save) and to each call's own `dst` (at match time).
    phone: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # Lowercased добавочный (Zeon's own `exten`/`members` values are plain
    # digit strings in practice, but compared case-insensitively like phone
    # line-names for consistency).
    extension: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<WorkshopPhoneMapping phone={self.phone!r} "
            f"ext={self.extension!r} -> {self.workshop_id}>"
        )
