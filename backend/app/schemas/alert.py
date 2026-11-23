from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AlertStatus = Literal["open", "in_review", "resolved"]
AlertSeverity = Literal["low", "medium", "high", "critical"]
Disposition = Literal["confirmed_fraud", "legitimate", "unresolved"]


class AlertListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transaction_id: uuid.UUID
    prediction_id: uuid.UUID
    severity: AlertSeverity
    status: AlertStatus
    reason_codes: list[str]
    assigned_to: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class AlertListResponse(BaseModel):
    items: list[AlertListItem]
    total: int
    limit: int
    offset: int


class PredictionSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fraud_probability: Decimal
    risk_score: Decimal
    risk_band: str
    prediction: str
    rule_hits: list[dict]
    model_version: str
    feature_schema_version: str
    created_at: datetime


class TransactionSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_transaction_id: str
    customer_id: uuid.UUID
    amount: Decimal
    currency: str
    transaction_type: str
    merchant_reference: str | None
    occurred_at: datetime
    received_at: datetime
    status: str


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reviewer_id: uuid.UUID
    disposition: Disposition
    notes: str
    reviewed_at: datetime


class AlertDetail(BaseModel):
    alert: AlertListItem
    transaction: TransactionSnapshot
    prediction: PredictionSnapshot
    reviews: list[ReviewOut] = Field(default_factory=list)


class AlertUpdate(BaseModel):
    status: AlertStatus | None = None
    severity: AlertSeverity | None = None
    assigned_to: uuid.UUID | None = None
    reason: str = Field(min_length=3, max_length=500)


class ReviewCreate(BaseModel):
    disposition: Disposition
    notes: str = Field(min_length=5, max_length=2000)
