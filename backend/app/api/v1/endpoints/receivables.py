"""Read API for the Финансы -> Дебиторская задолженность tab - see
services/receivables_service.py.

Same bearer-token protection as the rest of the read API - see
endpoints/settings.py's docstring for the same reasoning.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.db.session import get_db
from app.schemas.receivables import ReceivablesAgingResponse
from app.services import receivables_service

router = APIRouter(
    prefix="/receivables", tags=["receivables"], dependencies=[Depends(verify_api_token)]
)


@router.get("/aging", response_model=ReceivablesAgingResponse)
def read_receivables_aging(db: Session = Depends(get_db)) -> ReceivablesAgingResponse:
    return receivables_service.get_aging_report(db)
