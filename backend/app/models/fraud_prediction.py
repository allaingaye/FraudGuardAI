import uuid
from datetime import datetime
from typing import Any

from app.db.session import Base
from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column


class FraudPrediction(Base):
    __tablename__ = "fraud_predictions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    fraud_probability: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    rule_score: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    risk_score: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, index=True)
    risk_band: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    prediction: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_hits: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    explanation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (Index("ix_fraud_predictions_tx_created", "transaction_id", "created_at"),)
