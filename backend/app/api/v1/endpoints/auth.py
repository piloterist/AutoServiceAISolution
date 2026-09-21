"""Login verification for the per-user auth layer.

Called by the Next.js server (never the browser directly) on the existing
static Bearer token, same trust boundary as every other endpoint in this
API (see app/api/deps.py) - this endpoint only checks login+password
against app.models.user.User and returns who the user is; Next.js is the
one that turns that into a signed session cookie (see frontend/lib/auth.ts).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.db.session import get_db
from app.models.department import Department
from app.schemas.admin import AuthenticatedUser, LoginRequest
from app.services.auth_service import authenticate

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(verify_api_token)])


@router.post("/login", response_model=AuthenticatedUser)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthenticatedUser:
    user = authenticate(db, payload.login, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid login or password"
        )

    department_name = None
    if user.department_id is not None:
        department = db.get(Department, user.department_id)
        department_name = department.name if department else None

    return AuthenticatedUser(
        id=user.id,
        full_name=user.full_name,
        login=user.login,
        role=user.role,
        department_id=user.department_id,
        department_name=department_name,
        workshop_id=user.workshop_id,
    )
