from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.ml.features import (
    FEATURE_COLUMNS,
    FEATURE_SCHEMA_VERSION,
    build_features,
    features_to_vector,
)
from app.services.risk_scorer import score
from app.services.rule_engine import (
    RuleHit,
    check_high_velocity,
    check_new_device,
    check_night_transaction,
    check_unusual_amount,
    evaluate_rules,
    total_rule_points,
)


class TestFeatures:
    def test_schema_version(self):
        assert FEATURE_SCHEMA_VERSION == "1.0.0"

    def test_columns_order(self):
        assert FEATURE_COLUMNS == (
            "amount",
            "hour_of_day",
            "day_of_week",
            "is_weekend",
            "is_night",
            "amount_log",
            "currency_risk",
            "type_encoded",
        )

    def test_build_basic(self):
        f = build_features(
            amount="2500.00",
            currency="USD",
            transaction_type="online_payment",
            occurred_at=datetime(2026, 11, 8, 16, 30, tzinfo=UTC),
        )
        assert f.amount == 2500.0
        assert f.hour_of_day == 16
        assert f.is_weekend == 1  # 2026-11-08 is Sunday
        assert f.is_night == 0
        assert f.currency_risk == 0.1
        assert f.type_encoded == 1

    def test_night_flagged(self):
        f = build_features(
            amount=1000,
            currency="USD",
            transaction_type="card_payment",
            occurred_at=datetime(2026, 11, 8, 3, 0, tzinfo=UTC),
        )
        assert f.is_night == 1

    def test_unknown_type_safe(self):
        f = build_features(
            amount=100,
            currency="USD",
            transaction_type="something_new",
            occurred_at=datetime.now(UTC),
        )
        assert f.type_encoded == 5

    def test_unknown_currency_raises(self):
        with pytest.raises(ValueError, match="unsupported currency"):
            build_features(
                amount=100,
                currency="XYZ",
                transaction_type="card_payment",
                occurred_at=datetime.now(UTC),
            )

    def test_negative_amount_raises(self):
        with pytest.raises(ValueError):
            build_features(
                amount=-1,
                currency="USD",
                transaction_type="card_payment",
                occurred_at=datetime.now(UTC),
            )

    def test_vector_length(self):
        f = build_features(
            amount=100,
            currency="USD",
            transaction_type="card_payment",
            occurred_at=datetime.now(UTC),
        )
        assert len(features_to_vector(f)) == len(FEATURE_COLUMNS)


class TestRuleEngine:
    def test_unusual_amount(self):
        assert check_unusual_amount(amount=Decimal("6000")) is not None
        assert check_unusual_amount(amount=Decimal("100")) is None

    def test_high_velocity(self):
        assert check_high_velocity(recent_count=7) is not None
        assert check_high_velocity(recent_count=3) is None

    def test_night(self):
        assert (
            check_night_transaction(
                occurred_at=datetime(2026, 11, 8, 2, 0, tzinfo=UTC),
                amount=Decimal("1000"),
            )
            is not None
        )
        assert (
            check_night_transaction(
                occurred_at=datetime(2026, 11, 8, 2, 0, tzinfo=UTC),
                amount=Decimal("100"),
            )
            is None
        )

    def test_new_device(self):
        assert check_new_device(device_reference="d1", known_devices={"d2"}) is not None
        assert check_new_device(device_reference="d1", known_devices={"d1"}) is None

    def test_evaluate_combines(self):
        hits = evaluate_rules(
            amount=Decimal("6000"),
            occurred_at=datetime(2026, 11, 8, 2, 0, tzinfo=UTC),
            recent_tx_count=10,
            device_reference="new-dev",
            known_devices={"old-dev"},
        )
        codes = {h.reason_code for h in hits}
        assert codes == {
            "UNUSUAL_AMOUNT",
            "HIGH_VELOCITY",
            "NIGHT_TRANSACTION",
            "NEW_DEVICE",
        }

    def test_total_points(self):
        assert (
            total_rule_points([RuleHit("A", "A", 30.0, "d"), RuleHit("B", "B", 25.0, "d")]) == 55.0
        )


class TestRiskScorer:
    def test_low(self):
        r = score(model_probability=0.05, rule_hits=[])
        assert r.risk_band == "low"
        assert r.prediction == "likely_legitimate"

    def test_high(self):
        r = score(
            model_probability=0.99,
            rule_hits=[RuleHit("A", "A", 90.0, "d"), RuleHit("B", "B", 40.0, "d")],
        )
        assert r.risk_band == "high"
        assert r.prediction == "potentially_suspicious"
        assert r.risk_score >= 70.0

    def test_bounded(self):
        r = score(model_probability=1.0, rule_hits=[RuleHit("A", "A", 999.0, "d")])
        assert 0.0 <= r.risk_score <= 100.0

    def test_invalid_prob_raises(self):
        with pytest.raises(ValueError):
            score(model_probability=1.5, rule_hits=[])

    def test_weights(self):
        from app.services import risk_scorer

        assert abs((risk_scorer.MODEL_WEIGHT + risk_scorer.RULE_WEIGHT) - 1.0) < 1e-9

    def test_deterministic(self):
        args = {"model_probability": 0.6, "rule_hits": [RuleHit("A", "A", 25.0, "d")]}
        assert score(**args).risk_score == score(**args).risk_score
