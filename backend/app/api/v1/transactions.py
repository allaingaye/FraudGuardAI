from app.api.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.transaction import (
    TransactionCreate,
    TransactionListItem,
    TransactionListResponse,
    TransactionResponse,
)
from app.services.transaction_service import (
    DuplicateTransactionError,
    IdempotencyConflictError,
    process_transaction,
)
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post(
    "",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_transaction(
    body: TransactionCreate,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128),
    db: Session = Depends(get_db),
    current: User = Depends(require_role("admin", "analyst")),
) -> TransactionResponse:
    """Ingest and score a transaction. Requires `Idempotency-Key` header."""
    request_id = request.headers.get("X-Request-ID")
    try:
        return process_transaction(
            db,
            payload=body,
            idempotency_key=idempotency_key,
            actor_user_id=current.id,
            request_id=request_id,
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DuplicateTransactionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("", response_model=TransactionListResponse)
def list_transactions(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TransactionListResponse:
    total = db.query(Transaction).count()
    rows = (
        db.query(Transaction)
        .order_by(Transaction.occurred_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    items = [TransactionListItem.model_validate(r) for r in rows]
    return TransactionListResponse(items=items, total=total, limit=limit, offset=offset)
