"""A lead submitted through one of pan-motors.ru's own forms (quiz, "Получить
консультацию", "Рассрочка") - see services/leads_service.py for the intake
endpoint these arrive through, and product spec (2026-09-29 brief) for the
site-side field contract this was reverse-engineered from.

The site has no per-lead structure we control (a client-run WordPress theme,
different field sets per form) - rather than modeling each form's fields as
columns (which breaks the moment the site's own forms change), this stores
whatever JSON the site posts verbatim in `raw_payload`, and only pulls out
the handful of fields every lead needs regardless of source: `source` (which
form), `phone` (for matching against telephony_calls - see
services/leads_service.get_open_leads), `name` (not every form collects
one), and `created_at`.
"""

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SOURCE_QUIZ_BODY = "quiz_body"
SOURCE_QUIZ_MECHANICAL = "quiz_mechanical"
SOURCE_CONSULTATION = "consultation"
SOURCE_INSTALLMENT = "installment"
SOURCE_OTHER = "other"
SOURCES = (
    SOURCE_QUIZ_BODY,
    SOURCE_QUIZ_MECHANICAL,
    SOURCE_CONSULTATION,
    SOURCE_INSTALLMENT,
    SOURCE_OTHER,
)


class WebsiteLead(Base):
    __tablename__ = "website_leads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # One of the SOURCES constants above - see services/leads_service.py's
    # _classify_source for how the site's raw `form_name`/`quiz_damage[...]`
    # fields map to this.
    source: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    # Normalized to the last 10 digits - same convention as
    # telephony_calls.client (see services/zeon_client.py's _norm_phone) so
    # a lead can be matched against a real outbound call to the same
    # number, regardless of a leading 7/8/+7.
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Photo URLs, when the form had any (see the kuzovnoy quiz's Dropzone
    # upload) - also duplicated inside raw_payload, kept as its own column
    # so the "Заявки" page can show a photo strip without parsing payload
    # shape per source.
    photos: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    # Verbatim POST body from the site (minus recaptcha_response - see
    # leads_service.create_lead) - every quiz-specific field (damage list,
    # budget, gift, evacuator, messenger preference, auto_marka, page_url,
    # adv_channel, ...) lives here rather than as dedicated columns, since
    # the field set is entirely the client site's own and already varies by
    # form today.
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WebsiteLead {self.source} {self.phone}>"
