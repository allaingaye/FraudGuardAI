"""Risk scoring: combine rule hits + ML probability into a 0-100 score."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.rule_engine import RuleHit

MODEL_WEIGHT = 0.70
RULE_WEIGHT = 0.30
RULE_POINTS_CEILING = 100.0


@dataclass(frozen=True)
class RiskResult:
    risk_score: float
    risk_band: str
    prediction: str
    rule_hits: list[dict[str, Any]]
    rule_points: float
    model_probability: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "risk_score": self.risk_score,
            "risk_band": self.risk_band,
            "prediction": self.prediction,
            "rule_hits": self.rule_hits,
            "rule_points": self.rule_points,
            "model_probability": self.model_probability,
        }


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _band(score: float) -> tuple[str, str]:
    if score >= 70.0:
        return "high", "potentially_suspicious"
    if score >= 30.0:
        return "medium", "review"
    return "low", "likely_legitimate"


def score(
    *,
    model_probability: float,
    rule_hits: list[RuleHit],
) -> RiskResult:
    if not 0.0 <= model_probability <= 1.0:
        raise ValueError("model_probability must be between 0 and 1")

    p = float(model_probability)
    rule_points = float(sum(h.risk_points for h in rule_hits))
    rule_component = _clip(rule_points / RULE_POINTS_CEILING, 0.0, 1.0)

    raw = (MODEL_WEIGHT * p + RULE_WEIGHT * rule_component) * 100.0
    risk_score = round(_clip(raw, 0.0, 100.0), 2)

    band, prediction = _band(risk_score)

    return RiskResult(
        risk_score=risk_score,
        risk_band=band,
        prediction=prediction,
        rule_hits=[h.as_dict() for h in rule_hits],
        rule_points=round(rule_points, 2),
        model_probability=round(p, 4),
    )
