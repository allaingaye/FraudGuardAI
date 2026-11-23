import uuid

from app.api.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.user import User
from app.schemas.alert import AlertDetail, AlertListResponse, AlertUpdate, ReviewCreate
from app.services.alert_service import (
    AlertNotFoundError,
    AlertReviewConflictError,
    AlertStateError,
    get_alert,
    list_alerts,
    submit_review,
    update_alert,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=AlertListResponse)
def list_alerts_endpoint(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    status_: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AlertListResponse:
    items, total = list_alerts(db, status=status_, severity=severity, limit=limit, offset=offset)
    return AlertListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{alert_id}", response_model=AlertDetail)
def get_alert_endpoint(
    alert_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AlertDetail:
    try:
        return get_alert(db, alert_id)
    except AlertNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{alert_id}", response_model=AlertDetail)
def update_alert_endpoint(
    alert_id: uuid.UUID,
    body: AlertUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_role("admin", "analyst")),
) -> AlertDetail:
    request_id = request.headers.get("X-Request-ID")
    try:
        return update_alert(db, alert_id=alert_id, payload=body, actor=actor, request_id=request_id)
    except AlertNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AlertStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/{alert_id}/reviews",
    response_model=AlertDetail,
    status_code=status.HTTP_201_CREATED,
)
def submit_review_endpoint(
    alert_id: uuid.UUID,
    body: ReviewCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_role("analyst")),
) -> AlertDetail:
    request_id = request.headers.get("X-Request-ID")
    try:
        return submit_review(
            db, alert_id=alert_id, payload=body, actor=actor, request_id=request_id
        )
    except AlertNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AlertReviewConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
