from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.user import UserRead
from app.services.auth_service import (
    authenticate,
    issue_token,
    record_login_failure,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    request_id = request.headers.get("X-Request-ID")
    user = authenticate(db, email=body.email, password=body.password)
    if user is None:
        record_login_failure(db, email=body.email, request_id=request_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = issue_token(db, user=user, request_id=request_id)
    return TokenResponse(
        access_token=token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserRead.model_validate(user),
    )


@router.get("/me", response_model=UserRead)
def me(current: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(current)
