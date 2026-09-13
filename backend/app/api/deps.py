"""Shared FastAPI dependencies."""

from fastapi import Header, HTTPException, status

from app.core.config import get_settings


def verify_api_token(authorization: str | None = Header(default=None)) -> None:
    """Validate `Authorization: Bearer <API_TOKEN>`.

    The expected token is configurable per deployed instance via the
    API_TOKEN environment variable - never hardcoded.
    """
    settings = get_settings()

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = authorization.removeprefix("Bearer ").strip()
    if token != settings.api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")
