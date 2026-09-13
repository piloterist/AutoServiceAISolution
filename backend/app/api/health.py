"""Liveness endpoint, intentionally outside /api/v1 - used by orchestrators too."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
