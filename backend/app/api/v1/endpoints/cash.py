"""Касса (cash book) - see services/cash_service.py for the rules.

Same bearer-token protection as the rest of the API. Who is asking comes from
the X-Actor-User-Id / X-Actor-Name headers the Next.js proxy sets from the
caller's own session (same as the Planner) - the service uses that id to
decide which cash desks the caller may see, so a page can never ask for
another desk's book.
"""

import uuid
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.api.v1.endpoints.planner import actor
from app.db.session import get_db
from app.schemas.cash import (
    CashBookResponse,
    CashContextResponse,
    CashEntryOut,
    CashEntryResult,
    CashEntryWrite,
    CashSearchHit,
    CashWorkOrderOut,
)
from app.services import cash_export_service, cash_service
from app.services.cash_service import (
    CashError,
    CashForbidden,
    CashInvalid,
    CashLocked,
    CashNotFound,
)

router = APIRouter(prefix="/cash", tags=["cash"], dependencies=[Depends(verify_api_token)])


def _http_error(exc: CashError) -> HTTPException:
    if isinstance(exc, CashForbidden):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, CashNotFound):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, CashLocked):
        code = status.HTTP_423_LOCKED
    elif isinstance(exc, CashInvalid):
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    else:  # pragma: no cover - every subclass is handled above
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))


def _entry_out(db: Session, entry) -> CashEntryOut:
    out = CashEntryOut.model_validate(
        {**{k: getattr(entry, k) for k in cash_service._ENTRY_FIELDS}, "locked": False}
    )
    out.locked = cash_service.is_locked(db, entry.entry_date)
    return out


@router.get("/context", response_model=CashContextResponse)
def context(
    who: tuple[uuid.UUID | None, str] = Depends(actor), db: Session = Depends(get_db)
) -> CashContextResponse:
    """The cash desks the caller may see, and the one to open by default."""
    return CashContextResponse.model_validate(cash_service.get_context(db, who[0]))


@router.get("/book", response_model=CashBookResponse)
def book(
    workshop_id: uuid.UUID,
    date_from: date,
    date_to: date | None = None,
    who: tuple[uuid.UUID | None, str] = Depends(actor),
    db: Session = Depends(get_db),
) -> CashBookResponse:
    """Opening/closing cash balance, totals and entries of one cash desk for
    [date_from, date_to] (a single day when date_to is omitted)."""
    access = cash_service.get_access(db, who[0])
    try:
        return CashBookResponse.model_validate(
            cash_service.get_book(db, access, workshop_id, date_from, date_to or date_from)
        )
    except CashError as exc:
        raise _http_error(exc) from exc


XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/export")
def export_excel(
    workshop_id: uuid.UUID,
    date_from: date,
    date_to: date,
    who: tuple[uuid.UUID | None, str] = Depends(actor),
    db: Session = Depends(get_db),
) -> Response:
    """Every operation of one cash desk over [date_from, date_to] as an Excel table
    (Год / Месяц / День / Операция / Сумма, two balance rows for every day)."""
    access = cash_service.get_access(db, who[0])
    try:
        rows = cash_export_service.export_rows(db, access, workshop_id, date_from, date_to)
    except CashError as exc:
        raise _http_error(exc) from exc
    label = cash_service._workshop_label(db, workshop_id).replace("/", "-")
    filename = f"Касса {label} {date_from:%d.%m.%Y}-{date_to:%d.%m.%Y}.xlsx"
    return Response(
        content=cash_export_service.build_workbook(rows),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/search", response_model=list[CashSearchHit])
def search(
    workshop_id: uuid.UUID,
    q: str = Query(default=""),
    who: tuple[uuid.UUID | None, str] = Depends(actor),
    db: Session = Depends(get_db),
) -> list[CashSearchHit]:
    """Entries of this desk by work-order number, earliest first."""
    access = cash_service.get_access(db, who[0])
    try:
        rows = cash_service.search_entries(db, access, workshop_id, q)
    except CashError as exc:
        raise _http_error(exc) from exc
    return [CashSearchHit.model_validate(r, from_attributes=True) for r in rows]


@router.get("/work-orders", response_model=list[CashWorkOrderOut])
def work_orders(
    workshop_id: uuid.UUID,
    q: str = Query(default=""),
    who: tuple[uuid.UUID | None, str] = Depends(actor),
    db: Session = Depends(get_db),
) -> list[CashWorkOrderOut]:
    """The dialog's work-order list: this workshop's orders of the last 100
    days, narrowed by what was typed."""
    access = cash_service.get_access(db, who[0])
    try:
        rows = cash_service.search_work_orders(db, access, workshop_id, q)
    except CashError as exc:
        raise _http_error(exc) from exc
    return [CashWorkOrderOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/entries", response_model=CashEntryOut, status_code=status.HTTP_201_CREATED)
def create_entry(
    payload: CashEntryWrite,
    who: tuple[uuid.UUID | None, str] = Depends(actor),
    db: Session = Depends(get_db),
) -> CashEntryOut:
    access = cash_service.get_access(db, who[0])
    try:
        entry = cash_service.create_entry(
            db,
            access,
            workshop_id=payload.workshop_id,
            entry_date=payload.entry_date,
            kind=payload.kind,
            amount=payload.amount,
            comment=payload.comment,
            work_order_id=payload.work_order_id,
            work_order_number=payload.work_order_number,
            actor_user_id=who[0],
            actor_name=who[1],
        )
    except CashError as exc:
        raise _http_error(exc) from exc
    return _entry_out(db, entry)


@router.put("/entries/{entry_id}", response_model=CashEntryResult)
def update_entry(
    entry_id: uuid.UUID,
    payload: CashEntryWrite,
    who: tuple[uuid.UUID | None, str] = Depends(actor),
    db: Session = Depends(get_db),
) -> CashEntryResult:
    """Edits an entry; a zero amount deletes it (`deleted: true`)."""
    access = cash_service.get_access(db, who[0])
    try:
        entry = cash_service.update_entry(
            db,
            access,
            entry_id,
            entry_date=payload.entry_date,
            kind=payload.kind,
            amount=payload.amount,
            comment=payload.comment,
            work_order_id=payload.work_order_id,
            work_order_number=payload.work_order_number,
            actor_user_id=who[0],
            actor_name=who[1],
        )
    except CashError as exc:
        raise _http_error(exc) from exc
    if entry is None:
        return CashEntryResult(deleted=True, entry=None)
    return CashEntryResult(deleted=False, entry=_entry_out(db, entry))


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(
    entry_id: uuid.UUID,
    who: tuple[uuid.UUID | None, str] = Depends(actor),
    db: Session = Depends(get_db),
) -> None:
    access = cash_service.get_access(db, who[0])
    try:
        cash_service.delete_entry(db, access, entry_id, actor_user_id=who[0], actor_name=who[1])
    except CashError as exc:
        raise _http_error(exc) from exc
