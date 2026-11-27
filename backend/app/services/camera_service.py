"""Справочник камер: CRUD и запись текущего IP, который присылает узел (models/camera.py)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.camera import Camera

_NOT_HEX = re.compile(r"[^0-9A-Fa-f]")


def normalize_mac(value: str) -> str:
    """'9ca2f4da22ea' / '9c:a2:f4:da:22:ea' / '9C-A2-F4-DA-22-EA' -> '9C-A2-F4-DA-22-EA'."""
    digits = _NOT_HEX.sub("", value).upper()
    if len(digits) != 12:
        raise ValueError("MAC-адрес - это 12 шестнадцатеричных цифр, например 9C-A2-F4-DA-22-EA")
    return "-".join(digits[i : i + 2] for i in range(0, 12, 2))


def list_cameras(db: Session) -> list[Camera]:
    return list(db.scalars(select(Camera).order_by(Camera.code)))


def create_camera(
    db: Session, *, code: str, mac: str, name: str | None, model: str | None, note: str | None
) -> Camera:
    camera = Camera(code=code, mac=normalize_mac(mac), name=name, model=model, note=note)
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera


def update_camera(
    db: Session,
    camera_id: uuid.UUID,
    *,
    code: str,
    mac: str,
    name: str | None,
    model: str | None,
    note: str | None,
) -> Camera | None:
    camera = db.get(Camera, camera_id)
    if camera is None:
        return None
    new_mac = normalize_mac(mac)
    if new_mac != camera.mac:
        camera.ip = None  # другая камера - прежний IP ей не принадлежит
        camera.ip_seen_at = None
    camera.code, camera.mac = code, new_mac
    camera.name, camera.model, camera.note = name, model, note
    db.commit()
    db.refresh(camera)
    return camera


def delete_camera(db: Session, camera_id: uuid.UUID) -> bool:
    camera = db.get(Camera, camera_id)
    if camera is None:
        return False
    db.delete(camera)
    db.commit()
    return True


def record_ip(db: Session, camera_code: str, ip: str) -> None:
    """Узел нашёл камеру по MAC и сообщает её текущий IP (вместе с сигналом «я на связи»)."""
    camera = db.scalar(select(Camera).where(Camera.code == camera_code))
    if camera is not None:
        camera.ip = ip
        camera.ip_seen_at = datetime.now(UTC)
