from app.api.v1 import alerts, auth, transactions
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(transactions.router)
router.include_router(alerts.router)

__all__ = ["router"]
