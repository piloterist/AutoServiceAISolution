"""Integration API used by 1C/Alpha-Auto to push Work Order data."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.db.session import get_db
from app.schemas.import_work_order import ImportWorkOrdersRequest, ImportWorkOrdersResponse
from app.services.import_service import ImportProcessingError, process_work_order_import

router = APIRouter(tags=["import"])


@router.post(
    "/import/work-orders",
    response_model=ImportWorkOrdersResponse,
    dependencies=[Depends(verify_api_token)],
)
def import_work_orders(
    payload: ImportWorkOrdersRequest,
    db: Session = Depends(get_db),
) -> ImportWorkOrdersResponse:
    try:
        batch = process_work_order_import(db, payload)
    except ImportProcessingError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Import failed: {exc}",
        ) from exc

    return ImportWorkOrdersResponse(
        status="ok",
        received=batch.records_received,
        inserted=batch.records_inserted,
        updated=batch.records_updated,
        batch_id=batch.batch_id,
    )
