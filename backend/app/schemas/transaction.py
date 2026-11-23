from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP", "CAD", "AUD", "CHF", "JPY"}

SUPPORTED_TRANSACTION_TYPES = {
    "card_payment",
    "online_payment",
    "bank_transfer",
    "cash_withdrawal",
    "mobile_payment",
}


class TransactionContext(BaseModel):
    country: str | None = Field(default=None, max_length=2)
    device_reference: str | None = Field(default=None, max_length=128)
    ip_address: str | None = Field(default=None, max_length=64)


class TransactionCreate(BaseModel):
    external_transaction_id: str = Field(min_length=1, max_length=128)
    customer_reference: str = Field(min_length=1, max_length=128)
    amount: Decimal = Field(gt=0, le=Decimal("10000000.00"))
    currency: str = Field(min_length=3, max_length=3)
    transaction_type: str = Field(min_length=1, max_length=64)
    merchant_reference: str | None = Field(default=None, max_length=128)
    occurred_at: datetime
    context: TransactionContext = Field(default_factory=TransactionContext)

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, v: str) -> str:
        v = v.upper()
        if v not in SUPPORTED_CURRENCIES:
            raise ValueError(f"unsupported currency: {v}")
        return v

    @field_validator("transaction_type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in SUPPORTED_TRANSACTION_TYPES:
            raise ValueError(f"unsupported transaction_type: {v}")
        return v


class RuleHitOut(BaseModel):
    rule_name: str
    reason_code: str
    risk_points: float
    description: str
    severity: str


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: uuid.UUID
    external_transaction_id: str
    customer_reference: str
    amount: Decimal
    currency: str
    transaction_type: str
    occurred_at: datetime
    status: str

    prediction: str
    fraud_probability: float
    risk_score: float
    risk_band: str
    rule_hits: list[RuleHitOut]
    model_version: str
    feature_schema_version: str

    alert_id: uuid.UUID | None = None
    alert_severity: str | None = None

    idempotency_key: str
    replayed: bool = False


class TransactionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_transaction_id: str
    customer_id: uuid.UUID
    amount: Decimal
    currency: str
    transaction_type: str
    occurred_at: datetime
    status: str
    received_at: datetime


class TransactionListResponse(BaseModel):
    items: list[TransactionListItem]
    total: int
    limit: int
    offset: int
