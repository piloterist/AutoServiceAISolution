"""Справочник камер видеоконтроля (Настройки -> Камеры, product ask, 2026-11-27).

Камера опознаётся по MAC-адресу: IP у неё меняется (задан вручную или выдан роутером и
сменился после сбоя питания), а MAC - нет (он на наклейке на корпусе). Узел на площадке
забирает этот список, находит IP каждой камеры по MAC в локальной сети и присылает текущий IP
вместе с сигналом «я на связи» (см. services/camera_service.py, bay_service.record_heartbeat).
`code` - тот же код камеры, что у бокса/ворот («Камера» на странице «Боксы») и в bays.toml узла.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    # «9C-A2-F4-DA-22-EA»: заглавные, через дефис (services/camera_service.normalize_mac).
    mac: Mapped[str] = mapped_column(String(17), nullable=False, unique=True)
    # Что снимает камера: "bay" - бокс (слежение за въездом/выездом), "gate" - ворота
    # кузовного цеха (проезд под камерой). По нему узел заводит камеру, найденную по MAC.
    mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default="bay", server_default="bay"
    )
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Текущий IP: его присылает узел, найдя камеру по MAC (вручную не вводится).
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    ip_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Camera {self.code} {self.mac} {self.ip}>"
