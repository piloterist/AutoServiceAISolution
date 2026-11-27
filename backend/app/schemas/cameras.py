import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.services.camera_service import normalize_mac


class CameraWrite(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    mac: str
    mode: Literal["bay", "gate"] = "bay"
    name: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    note: str | None = None

    @field_validator("code")
    @classmethod
    def _strip_code(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("code is empty")
        return value

    @field_validator("mac")
    @classmethod
    def _mac(cls, value: str) -> str:
        return normalize_mac(value)


class CameraIpReport(BaseModel):
    """Узел нашёл камеру по MAC и сообщает её текущий IP."""

    code: str = Field(min_length=1, max_length=50)
    ip: str = Field(min_length=7, max_length=45)


class CameraOut(BaseModel):
    id: uuid.UUID
    code: str
    mac: str
    mode: str
    name: str | None
    model: str | None
    note: str | None
    ip: str | None
    ip_seen_at: datetime | None
    # Из сигнала узла (camera_status): когда узел последний раз выходил на связь и отдаёт ли
    # камера видео; None - узел по этой камере ещё ни разу не писал.
    node_seen_at: datetime | None = None
    camera_ok: bool | None = None

    model_config = {"from_attributes": True}
