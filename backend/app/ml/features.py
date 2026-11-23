"""Deterministic feature builder.

The SAME function must run during training and at inference. Any change here
requires bumping FEATURE_SCHEMA_VERSION and retraining.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

FEATURE_SCHEMA_VERSION = "1.0.0"

# Features the model is trained on. ORDER MATTERS — inference must match training.
FEATURE_COLUMNS: tuple[str, ...] = (
    "amount",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "is_night",
    "amount_log",
    "currency_risk",
    "type_encoded",
)

CURRENCY_RISK: dict[str, float] = {
    "USD": 0.1,
    "EUR": 0.1,
    "GBP": 0.1,
    "CAD": 0.15,
    "AUD": 0.15,
    "CHF": 0.15,
    "JPY": 0.2,
}

TYPE_ENCODING: dict[str, int] = {
    "card_payment": 0,
    "online_payment": 1,
    "bank_transfer": 2,
    "cash_withdrawal": 3,
    "mobile_payment": 4,
    "unknown": 5,
}


@dataclass(frozen=True)
class TransactionFeatures:
    amount: float
    hour_of_day: int
    day_of_week: int
    is_weekend: int
    is_night: int
    amount_log: float
    currency_risk: float
    type_encoded: int

    def as_dict(self) -> dict[str, float]:
        return {
            "amount": self.amount,
            "hour_of_day": self.hour_of_day,
            "day_of_week": self.day_of_week,
            "is_weekend": self.is_weekend,
            "is_night": self.is_night,
            "amount_log": self.amount_log,
            "currency_risk": self.currency_risk,
            "type_encoded": self.type_encoded,
        }


def _safe_log(amount: float) -> float:
    return math.log1p(max(amount, 0.0))


def build_features(
    *,
    amount: Decimal | float | int | str,
    currency: str,
    transaction_type: str,
    occurred_at: datetime,
) -> TransactionFeatures:
    """Build a deterministic feature vector for one transaction."""
    amt = float(amount)
    if amt < 0:
        raise ValueError("amount must be non-negative")

    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    occurred_at = occurred_at.astimezone(UTC)

    cur = currency.upper()
    if cur not in CURRENCY_RISK:
        raise ValueError(f"unsupported currency: {cur}")

    tx_type = transaction_type.strip().lower()
    type_code = TYPE_ENCODING.get(tx_type, TYPE_ENCODING["unknown"])

    hour = occurred_at.hour
    dow = occurred_at.weekday()  # Mon=0, Sun=6

    return TransactionFeatures(
        amount=amt,
        hour_of_day=hour,
        day_of_week=dow,
        is_weekend=1 if dow >= 5 else 0,
        is_night=1 if (hour < 6 or hour >= 22) else 0,
        amount_log=_safe_log(amt),
        currency_risk=CURRENCY_RISK[cur],
        type_encoded=type_code,
    )


def features_to_vector(f: TransactionFeatures) -> list[float]:
    d = f.as_dict()
    return [d[name] for name in FEATURE_COLUMNS]


def generate_request_id() -> str:
    return uuid.uuid4().hex
