"""Справочник камер (Настройки -> Камеры) и список MAC для узла на площадке.

Тот же bearer-токен, что и у остального API. Узел забирает GET /cameras (код + MAC), находит
IP по MAC в локальной сети и присылает его в сигнале «я на связи» (/bays/heartbeat).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.db.session import get_db
from app.models.bay import CameraStatus
from app.models.camera import Camera
from app.schemas.cameras import CameraIpReport, CameraOut, CameraWrite
from app.services import camera_service

router = APIRouter(prefix="/cameras", tags=["cameras"], dependencies=[Depends(verify_api_token)])


def _out(db: Session, camera: Camera) -> CameraOut:
    heartbeat = db.get(CameraStatus, camera.code)
    out = CameraOut.model_validate(camera)
    if heartbeat is not None:
        out.node_seen_at = heartbeat.seen_at
        out.camera_ok = heartbeat.camera_ok
    return out


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail="Камера с таким кодом или MAC уже есть"
    )


@router.get("", response_model=list[CameraOut])
def list_cameras(db: Session = Depends(get_db)) -> list[CameraOut]:
    return [_out(db, camera) for camera in camera_service.list_cameras(db)]


@router.post("", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
def create_camera(payload: CameraWrite, db: Session = Depends(get_db)) -> CameraOut:
    try:
        camera = camera_service.create_camera(db, **payload.model_dump())
    except Exception as exc:  # unique code / mac
        db.rollback()
        raise _conflict() from exc
    return _out(db, camera)


@router.post("/report-ip", status_code=status.HTTP_204_NO_CONTENT)
def report_camera_ip(payload: CameraIpReport, db: Session = Depends(get_db)) -> None:
    """Узел: «камеру с этим кодом нашёл по MAC на таком IP» (после сканирования сети)."""
    camera_service.record_ip(db, payload.code, payload.ip)
    db.commit()


@router.put("/{camera_id}", response_model=CameraOut)
def update_camera(
    camera_id: uuid.UUID, payload: CameraWrite, db: Session = Depends(get_db)
) -> CameraOut:
    try:
        camera = camera_service.update_camera(db, camera_id, **payload.model_dump())
    except Exception as exc:
        db.rollback()
        raise _conflict() from exc
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    return _out(db, camera)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(camera_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    if not camera_service.delete_camera(db, camera_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
