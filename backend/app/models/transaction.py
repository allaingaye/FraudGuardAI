import uuid
from datetime import datetime
from decimal import Decimal

from app.db.session import Base
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_transaction_id: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(64), nullable=False)
    merchant_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="received")
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)

    customer = relationship("Customer", back_populates="transactions")

    __table_args__ = (
        # Fast lookups for dashboard queries
        Index("ix_transactions_customer_occurred", "customer_id", "occurred_at"),
        Index("ix_transactions_occurred_at", "occurred_at"),
        Index("ix_transactions_status", "status"),
    )
