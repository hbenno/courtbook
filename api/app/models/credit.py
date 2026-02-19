"""Credit transaction model for tracking booking credits."""

import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.booking import Booking
    from app.models.member import User
    from app.models.organisation import Organisation


class TransactionType(enum.StrEnum):
    GRANT = "grant"
    BOOKING_PAYMENT = "booking_payment"
    CANCELLATION_CREDIT = "cancellation_credit"
    ADMIN_ADJUSTMENT = "admin_adjustment"
    PAYMENT_REVERSAL = "payment_reversal"


class CreditTransaction(TimestampMixin, Base):
    """A single credit movement — positive means credit in, negative means debit."""

    __tablename__ = "credit_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id"), nullable=False)
    amount_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, name="transaction_type", values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"))
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship(lazy="raise")
    organisation: Mapped["Organisation"] = relationship(lazy="raise")
    booking: Mapped["Booking | None"] = relationship(lazy="raise")

    __table_args__ = (Index("ix_credit_txn_user_org", "user_id", "organisation_id"),)

    def __repr__(self) -> str:
        return f"<CreditTransaction {self.transaction_type.value} {self.amount_pence}p user={self.user_id}>"
