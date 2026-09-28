"""Справочник источников звонков (Settings -> IP-телефония -> Источники) -
maps a raw telephony-provider line/number to a human name, group and
display order for the call-statistics page. See
services/telephony_stats_service.py, which joins this against
telephony_calls.line.

Client-specific data (which lines exist, what they're called, how they're
grouped) - never hardcoded, same reasoning as Department/Workshop. A line
seen in imported calls with no matching row here falls back to "Неизвестная
линия <line>" in the "Прочие" group at read time, rather than failing the
import - see telephony_stats_service.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

GROUP_MAPS = "Карты и каталоги"
GROUP_DIRECT_NUMBERS = "Прямые номера"
GROUP_OTHER = "Прочие"
SOURCE_GROUPS = (GROUP_MAPS, GROUP_DIRECT_NUMBERS, GROUP_OTHER)


class PhoneSource(Base):
    __tablename__ = "phone_sources"
    __table_args__ = (UniqueConstraint("line_code", name="uq_phone_sources_line_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # The raw value telephony_calls.line/provider "line" field carries
    # (e.g. "pan", "pan2", "79257111125") - whatever the provider sends,
    # passed through as-is, never normalized/guessed at (see
    # ARCHITECTURE.md's stance on WorkOrder.department/status).
    line_code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Small grey caption under the name on the stats page (e.g.
    # "pan2 · IVR Yamaps" or "+7 925 711-11-25 · IVR-1125").
    caption: Mapped[str | None] = mapped_column(String(255), nullable=True)
    group_name: Mapped[str] = mapped_column(String(50), nullable=False, default=GROUP_OTHER)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PhoneSource {self.line_code!r} {self.name!r}>"
