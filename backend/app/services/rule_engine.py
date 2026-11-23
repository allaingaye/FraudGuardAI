"""Deterministic rule-based detection. Pure functions, no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class RuleHit:
    rule_name: str
    reason_code: str
    risk_points: float
    description: str
    severity: str = "medium"

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_name": self.rule_name,
            "reason_code": self.reason_code,
            "risk_points": self.risk_points,
            "description": self.description,
            "severity": self.severity,
        }


DEFAULT_UNUSUAL_AMOUNT_THRESHOLD = Decimal("5000.00")
DEFAULT_VELOCITY_COUNT = 5
DEFAULT_VELOCITY_WINDOW_MINUTES = 10


def check_unusual_amount(
    *,
    amount: Decimal,
    threshold: Decimal = DEFAULT_UNUSUAL_AMOUNT_THRESHOLD,
    risk_points: float = 30.0,
) -> RuleHit | None:
    if amount >= threshold:
        return RuleHit(
            rule_name="UNUSUAL_AMOUNT",
            reason_code="UNUSUAL_AMOUNT",
            risk_points=risk_points,
            description=f"Amount {amount} >= threshold {threshold}",
            severity="medium",
        )
    return None


def check_high_velocity(
    *,
    recent_count: int,
    threshold_count: int = DEFAULT_VELOCITY_COUNT,
    window_minutes: int = DEFAULT_VELOCITY_WINDOW_MINUTES,
    risk_points: float = 25.0,
) -> RuleHit | None:
    if recent_count >= threshold_count:
        return RuleHit(
            rule_name="HIGH_VELOCITY",
            reason_code="HIGH_VELOCITY",
            risk_points=risk_points,
            description=f"{recent_count} tx in last {window_minutes}m >= {threshold_count}",
            severity="high",
        )
    return None


def check_night_transaction(
    *,
    occurred_at: datetime,
    amount: Decimal,
    min_amount: Decimal = Decimal("500.00"),
    risk_points: float = 10.0,
) -> RuleHit | None:
    if occurred_at.tzinfo is None:
        return None
    hour = occurred_at.hour
    if (hour < 6 or hour >= 22) and amount >= min_amount:
        return RuleHit(
            rule_name="NIGHT_TRANSACTION",
            reason_code="NIGHT_TRANSACTION",
            risk_points=risk_points,
            description=f"Amount {amount} at hour {hour} UTC",
            severity="low",
        )
    return None


def check_new_device(
    *,
    device_reference: str | None,
    known_devices: set[str],
    risk_points: float = 20.0,
) -> RuleHit | None:
    if device_reference and device_reference not in known_devices:
        return RuleHit(
            rule_name="NEW_DEVICE",
            reason_code="NEW_DEVICE",
            risk_points=risk_points,
            description=f"First time device {device_reference}",
            severity="medium",
        )
    return None


def evaluate_rules(
    *,
    amount: Decimal,
    occurred_at: datetime,
    recent_tx_count: int = 0,
    device_reference: str | None = None,
    known_devices: set[str] | None = None,
    enabled_rules: dict[str, dict[str, Any]] | None = None,
) -> list[RuleHit]:
    """Run rules.

    If `enabled_rules` is None -> ALL rules run with defaults.
    If `enabled_rules` is provided -> only listed rules run, with per-rule
    parameter overrides. Passing an empty dict explicitly disables all rules.
    """
    hits: list[RuleHit] = []

    def _enabled(name: str) -> bool:
        return enabled_rules is None or name in enabled_rules

    def _params(name: str) -> dict[str, Any]:
        if enabled_rules is None:
            return {}
        return enabled_rules.get(name, {})

    if _enabled("UNUSUAL_AMOUNT"):
        params = _params("UNUSUAL_AMOUNT")
        h = check_unusual_amount(
            amount=amount,
            threshold=Decimal(str(params.get("threshold", DEFAULT_UNUSUAL_AMOUNT_THRESHOLD))),
            risk_points=float(params.get("risk_points", 30.0)),
        )
        if h:
            hits.append(h)

    if _enabled("HIGH_VELOCITY"):
        params = _params("HIGH_VELOCITY")
        h = check_high_velocity(
            recent_count=recent_tx_count,
            threshold_count=int(params.get("threshold_count", DEFAULT_VELOCITY_COUNT)),
            window_minutes=int(params.get("window_minutes", DEFAULT_VELOCITY_WINDOW_MINUTES)),
            risk_points=float(params.get("risk_points", 25.0)),
        )
        if h:
            hits.append(h)

    if _enabled("NIGHT_TRANSACTION"):
        params = _params("NIGHT_TRANSACTION")
        h = check_night_transaction(
            occurred_at=occurred_at,
            amount=amount,
            min_amount=Decimal(str(params.get("min_amount", "500.00"))),
            risk_points=float(params.get("risk_points", 10.0)),
        )
        if h:
            hits.append(h)

    if _enabled("NEW_DEVICE") and device_reference:
        params = _params("NEW_DEVICE")
        h = check_new_device(
            device_reference=device_reference,
            known_devices=known_devices or set(),
            risk_points=float(params.get("risk_points", 20.0)),
        )
        if h:
            hits.append(h)

    return hits


def total_rule_points(hits: list[RuleHit]) -> float:
    return float(sum(h.risk_points for h in hits))
