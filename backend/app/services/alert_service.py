"""Alert investigation workflow.

Status transitions:
    open       -> in_review, resolved
    in_review  -> resolved
    resolved   -> (terminal)

Every state change requires a reason and writes an audit row. Reviews are
analyst-only and can only be submitted before the alert is resolved.
"""

from __future__ import annotations

import uuid

from app.models.analyst_review import AnalystReview
from app.models.fraud_alert import FraudAlert
from app.models.fraud_prediction import FraudPrediction
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.alert import (
    AlertDetail,
    AlertListItem,
    AlertUpdate,
    PredictionSnapshot,
    ReviewCreate,
    ReviewOut,
    TransactionSnapshot,
)
from app.services.audit_service import record_audit
from sqlalchemy.orm import Session


class AlertNotFoundError(Exception):
    pass


class AlertStateError(Exception):
    pass


class AlertReviewConflictError(Exception):
    pass


VALID_TRANSITIONS: dict[str, set[str]] = {
    "open": {"in_review", "resolved"},
    "in_review": {"resolved"},
    "resolved": set(),
}


def _list_item(alert: FraudAlert) -> AlertListItem:
    return AlertListItem.model_validate(alert)


def get_alert(db: Session, alert_id: uuid.UUID) -> AlertDetail:
    alert = db.get(FraudAlert, alert_id)
    if alert is None:
        raise AlertNotFoundError(f"alert not found: {alert_id}")

    tx = db.get(Transaction, alert.transaction_id)
    pred = db.get(FraudPrediction, alert.prediction_id)
    if tx is None or pred is None:
        raise AlertNotFoundError("alert references missing transaction or prediction")

    reviews = (
        db.query(AnalystReview)
        .filter(AnalystReview.alert_id == alert.id)
        .order_by(AnalystReview.reviewed_at.desc())
        .all()
    )

    return AlertDetail(
        alert=_list_item(alert),
        transaction=TransactionSnapshot.model_validate(tx),
        prediction=PredictionSnapshot.model_validate(pred),
        reviews=[ReviewOut.model_validate(r) for r in reviews],
    )


def list_alerts(
    db: Session,
    *,
    status: str | None = None,
    severity: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AlertListItem], int]:
    query = db.query(FraudAlert)
    if status:
        query = query.filter(FraudAlert.status == status)
    if severity:
        query = query.filter(FraudAlert.severity == severity)
    total = query.count()
    rows = query.order_by(FraudAlert.created_at.desc()).offset(offset).limit(limit).all()
    return [_list_item(a) for a in rows], total


def update_alert(
    db: Session,
    *,
    alert_id: uuid.UUID,
    payload: AlertUpdate,
    actor: User,
    request_id: str | None = None,
) -> AlertDetail:
    alert = db.get(FraudAlert, alert_id)
    if alert is None:
        raise AlertNotFoundError(f"alert not found: {alert_id}")

    before = {
        "status": alert.status,
        "severity": alert.severity,
        "assigned_to": str(alert.assigned_to) if alert.assigned_to else None,
    }

    if payload.status is not None and payload.status != alert.status:
        allowed = VALID_TRANSITIONS.get(alert.status, set())
        if payload.status not in allowed:
            raise AlertStateError(
                f"cannot transition status {alert.status!r} -> {payload.status!r}"
            )
        alert.status = payload.status

    if payload.severity is not None and payload.severity != alert.severity:
        alert.severity = payload.severity

    if payload.assigned_to is not None:
        assignee = db.get(User, payload.assigned_to)
        if assignee is None or not assignee.is_active:
            raise AlertStateError(f"assignee is invalid or inactive: {payload.assigned_to}")
        alert.assigned_to = payload.assigned_to

    after = {
        "status": alert.status,
        "severity": alert.severity,
        "assigned_to": str(alert.assigned_to) if alert.assigned_to else None,
    }

    db.flush()
    record_audit(
        db,
        action="alert.updated",
        actor_user_id=actor.id,
        entity_type="fraud_alert",
        entity_id=str(alert.id),
        before=before,
        after=after,
        reason=payload.reason,
        request_id=request_id,
    )
    db.commit()
    db.refresh(alert)
    return get_alert(db, alert.id)


def submit_review(
    db: Session,
    *,
    alert_id: uuid.UUID,
    payload: ReviewCreate,
    actor: User,
    request_id: str | None = None,
) -> AlertDetail:
    alert = db.get(FraudAlert, alert_id)
    if alert is None:
        raise AlertNotFoundError(f"alert not found: {alert_id}")

    if alert.status == "resolved":
        raise AlertReviewConflictError("alert already resolved; cannot add another review")

    review = AnalystReview(
        alert_id=alert.id,
        reviewer_id=actor.id,
        disposition=payload.disposition,
        notes=payload.notes,
    )
    db.add(review)

    previous_status = alert.status
    alert.status = "resolved"

    db.flush()
    record_audit(
        db,
        action="alert.reviewed",
        actor_user_id=actor.id,
        entity_type="fraud_alert",
        entity_id=str(alert.id),
        before={"status": previous_status},
        after={"status": "resolved", "disposition": payload.disposition},
        reason=payload.notes[:500],
        request_id=request_id,
    )
    db.commit()
    db.refresh(alert)
    return get_alert(db, alert.id)
