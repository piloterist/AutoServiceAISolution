"""Read API for the Cockpit landing page - see services/cockpit_service.py.

Same bearer-token protection as the rest of the read API (the frontend's
server proxies this, the browser never holds the token) - see
endpoints/settings.py's docstring for the same reasoning.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.db.session import get_db
from app.schemas.cockpit import CockpitSnapshotOut
from app.services import cockpit_service

router = APIRouter(prefix="/cockpit", tags=["cockpit"], dependencies=[Depends(verify_api_token)])


@router.get("", response_model=CockpitSnapshotOut)
def read_cockpit_snapshot(
    workshop_id: UUID | None = None,
    include_nzp: bool = False,
    year: int | None = None,
    month: int | None = Query(None, ge=1, le=12),
    db: Session = Depends(get_db),
) -> CockpitSnapshotOut:
    """Moscow-local calendar month - `year`/`month` omitted (both together)
    defaults to the current month to date (per product spec, 2026-09-30:
    "по умолчанию всегда должен показывать текущий" - supersedes the
    original spec's "произвольные периоды сейчас не нужны", now that
    Cockpit's own month/year picker exists). `workshop_id` omitted or null
    means the whole company."""
    snapshot = cockpit_service.get_snapshot(
        db, workshop_id=workshop_id, include_nzp=include_nzp, year=year, month=month
    )
    return CockpitSnapshotOut.model_validate(snapshot)
