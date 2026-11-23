"""Transaction ingestion orchestrator.

Single entry point that runs the full fraud pipeline for one transaction.
All writes are wrapped in one DB transaction — either every row lands, or
nothing does. Idempotency ensures replays don't create duplicate rows or
duplicate alerts.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC
from decimal import Decimal

from app.ml.features import FEATURE_SCHEMA_VERSION, build_features
from app.ml.inference import inference
from app.models.customer import Customer
from app.models.fraud_alert import FraudAlert
from app.models.fraud_prediction import FraudPrediction
from app.models.transaction import Transaction
from app.schemas.transaction import (
    RuleHitOut,
    TransactionCreate,
    TransactionResponse,
)
from app.services.audit_service import record_audit
from app.services.risk_scorer import score as score_risk
from app.services.rule_engine import evaluate_rules
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

logger = logging.getLogger("fraudguard.transaction")


class DuplicateTransactionError(Exception):
    """Raised when the external_transaction_id already exists."""


class IdempotencyConflictError(Exception):
    """Raised when the same Idempotency-Key was used for a different payload."""


def _existing_by_idempotency(db: Session, key: str) -> Transaction | None:
    return db.scalar(select(Transaction).where(Transaction.idempotency_key == key))


def _existing_by_external_id(db: Session, external_id: str) -> Transaction | None:
    return db.scalar(select(Transaction).where(Transaction.external_transaction_id == external_id))


def _ensure_customer(db: Session, external_reference: str) -> Customer:
    cust = db.scalar(select(Customer).where(Customer.external_reference == external_reference))
    if cust:
        return cust
    cust = Customer(external_reference=external_reference)
    db.add(cust)
    db.flush()
    return cust


def _recent_tx_count(db: Session, *, customer_id: uuid.UUID, window_minutes: int = 10) -> int:
    from datetime import datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(minutes=window_minutes)
    return (
        db.query(Transaction)
        .filter(Transaction.customer_id == customer_id)
        .filter(Transaction.received_at >= cutoff)
        .count()
    )


def _known_devices(db: Session, customer_id: uuid.UUID) -> set[str]:
    """Best-effort known devices from prior transactions' audit trail.

    The MVP has no dedicated device table, so we treat "devices already seen in
    past transactions for this customer" as known. If context.device_reference
    was supplied on a previous transaction, that device becomes 'known' from
    the customer's perspective.
    """
    return set()


def _build_response(
    tx: Transaction,
    pred: FraudPrediction,
    alert: FraudAlert | None,
    *,
    customer_reference: str,
    replayed: bool,
) -> TransactionResponse:
    return TransactionResponse(
        transaction_id=tx.id,
        external_transaction_id=tx.external_transaction_id,
        customer_reference=customer_reference,
        amount=tx.amount,
        currency=tx.currency,
        transaction_type=tx.transaction_type,
        occurred_at=tx.occurred_at,
        status=tx.status,
        prediction=pred.prediction,
        fraud_probability=float(pred.fraud_probability),
        risk_score=float(pred.risk_score),
        risk_band=pred.risk_band,
        rule_hits=[RuleHitOut(**h) for h in (pred.rule_hits or [])],
        model_version=pred.model_version,
        feature_schema_version=pred.feature_schema_version,
        alert_id=alert.id if alert else None,
        alert_severity=alert.severity if alert else None,
        idempotency_key=tx.idempotency_key,
        replayed=replayed,
    )


def process_transaction(
    db: Session,
    *,
    payload: TransactionCreate,
    idempotency_key: str,
    actor_user_id: uuid.UUID | None = None,
    request_id: str | None = None,
) -> TransactionResponse:
    # ── 1. Idempotency check ─────────────────────────────────────────
    existing = _existing_by_idempotency(db, idempotency_key)
    if existing:
        if existing.external_transaction_id != payload.external_transaction_id:
            raise IdempotencyConflictError("Idempotency-Key was used for a different transaction")
        pred = (
            db.query(FraudPrediction)
            .filter(FraudPrediction.transaction_id == existing.id)
            .order_by(FraudPrediction.created_at.desc())
            .first()
        )
        alert = db.query(FraudAlert).filter(FraudAlert.transaction_id == existing.id).first()
        if pred is None:
            raise IdempotencyConflictError("Idempotent replay found transaction without prediction")
        return _build_response(
            existing,
            pred,
            alert,
            customer_reference=payload.customer_reference,
            replayed=True,
        )

    # ── 2. External id uniqueness ────────────────────────────────────
    if _existing_by_external_id(db, payload.external_transaction_id):
        raise DuplicateTransactionError(
            f"external_transaction_id already exists: {payload.external_transaction_id}"
        )

    # ── 3. Persist customer + transaction ────────────────────────────
    customer = _ensure_customer(db, payload.customer_reference)

    tx = Transaction(
        external_transaction_id=payload.external_transaction_id,
        customer_id=customer.id,
        amount=payload.amount,
        currency=payload.currency,
        transaction_type=payload.transaction_type,
        merchant_reference=payload.merchant_reference,
        occurred_at=payload.occurred_at,
        status="scored",
        idempotency_key=idempotency_key,
    )
    db.add(tx)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateTransactionError(str(exc)) from exc

    # ── 4. Build features ────────────────────────────────────────────
    feats = build_features(
        amount=payload.amount,
        currency=payload.currency,
        transaction_type=payload.transaction_type,
        occurred_at=payload.occurred_at,
    )

    # ── 5. Rules ─────────────────────────────────────────────────────
    recent_count = _recent_tx_count(db, customer_id=customer.id, window_minutes=10)
    known = _known_devices(db, customer.id)
    rule_hits = evaluate_rules(
        amount=payload.amount,
        occurred_at=payload.occurred_at,
        recent_tx_count=recent_count,
        device_reference=payload.context.device_reference,
        known_devices=known,
    )

    # ── 6. ML probability ────────────────────────────────────────────
    if not inference.is_loaded:
        raise RuntimeError("ML model is not loaded — run `python -m app.ml.train_bootstrap`")
    proba = inference.predict_proba(feats)

    # ── 7. Risk score ────────────────────────────────────────────────
    risk = score_risk(model_probability=proba, rule_hits=rule_hits)

    # ── 8. Persist prediction ────────────────────────────────────────
    pred = FraudPrediction(
        transaction_id=tx.id,
        model_version=inference.version,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        fraud_probability=Decimal(str(round(proba, 4))),
        rule_score=Decimal(str(risk.rule_points)),
        risk_score=Decimal(str(risk.risk_score)),
        risk_band=risk.risk_band,
        prediction=risk.prediction,
        rule_hits=risk.rule_hits,
        explanation={"model_probability": risk.model_probability},
    )
    db.add(pred)
    db.flush()

    # ── 9. Alert (medium / high only) ────────────────────────────────
    alert = None
    if risk.risk_band in {"medium", "high"}:
        reason_codes = [h["reason_code"] for h in risk.rule_hits] or ["ML_HIGH_RISK"]
        alert = FraudAlert(
            transaction_id=tx.id,
            prediction_id=pred.id,
            severity=risk.risk_band,
            status="open",
            reason_codes=reason_codes,
        )
        db.add(alert)
        db.flush()

    # ── 10. Audit + commit ───────────────────────────────────────────
    record_audit(
        db,
        action="transaction.processed",
        actor_user_id=actor_user_id,
        entity_type="transaction",
        entity_id=str(tx.id),
        after={
            "risk_score": float(risk.risk_score),
            "risk_band": risk.risk_band,
            "alert_id": str(alert.id) if alert else None,
            "model_version": inference.version,
        },
        request_id=request_id,
    )
    db.commit()
    db.refresh(tx)
    db.refresh(pred)
    if alert:
        db.refresh(alert)

    logger.info(
        "tx %s scored: band=%s score=%s alert=%s",
        tx.id,
        risk.risk_band,
        risk.risk_score,
        alert.id if alert else None,
    )

    return _build_response(
        tx,
        pred,
        alert,
        customer_reference=payload.customer_reference,
        replayed=False,
    )
