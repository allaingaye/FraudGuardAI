from app.core.security import create_access_token, verify_password
from app.models.user import User
from app.services.audit_service import record_audit
from sqlalchemy import select
from sqlalchemy.orm import Session


def authenticate(db: Session, *, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def issue_token(db: Session, *, user: User, request_id: str | None = None) -> str:
    token = create_access_token(
        subject=str(user.id),
        extra_claims={"role": user.role, "email": user.email},
    )
    record_audit(
        db,
        action="auth.login.success",
        actor_user_id=user.id,
        entity_type="user",
        entity_id=str(user.id),
        request_id=request_id,
    )
    db.commit()
    return token


def record_login_failure(db: Session, *, email: str, request_id: str | None = None) -> None:
    record_audit(
        db,
        action="auth.login.failure",
        entity_type="user",
        entity_id=email.lower(),
        request_id=request_id,
    )
    db.commit()
