"""Booking model.

A booking reserves a resource (court) for a member at a specific date/time.
This is the core transactional entity in the system.
"""

from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    Time,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

import enum


class BookingStatus(str, enum.Enum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"
    COMPLETED = "completed"


class BookingSource(str, enum.Enum):
    MEMBER = "member"          # Self-service booking
    ADMIN = "admin"            # Admin-created
    FAIRNESS = "fairness"      # Allocated by fairness window
    PROGRAMME = "programme"    # Block-booked for coaching
    STANDING = "standing"      # Standing group reservation


class PaymentStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"  # Free booking
    PENDING = "pending"
    PAID = "paid"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class Booking(TimestampMixin, Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id"), nullable=False)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    # When
    booking_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(nullable=False)

    # Status
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status", values_callable=lambda e: [x.value for x in e]),
        default=BookingStatus.CONFIRMED,
        nullable=False,
    )
    source: Mapped[BookingSource] = mapped_column(
        Enum(BookingSource, name="booking_source", values_callable=lambda e: [x.value for x in e]),
        default=BookingSource.MEMBER,
        nullable=False,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)

    # Payment
    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status", values_callable=lambda e: [x.value for x in e]),
        default=PaymentStatus.NOT_REQUIRED,
        nullable=False,
    )
    amount_pence: Mapped[int] = mapped_column(default=0, nullable=False)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(100))

    # Metadata
    notes: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Relationships
    resource: Mapped["Resource"] = relationship()
    user: Mapped["User"] = relationship()

    __table_args__ = (
        # Prevent double-booking: no two confirmed bookings for the same resource
        # at the same date/time. Partial index on confirmed only.
        Index(
            "ix_bookings_no_double",
            "resource_id",
            "booking_date",
            "start_time",
            unique=True,
            postgresql_where="status = 'confirmed'",
        ),
        # Fast lookups by org + date (the booking grid)
        Index("ix_bookings_org_date", "organisation_id", "booking_date"),
        # Fast lookups by user (my bookings)
        Index("ix_bookings_user", "user_id", "booking_date"),
    )

    def __repr__(self) -> str:
        return f"<Booking {self.booking_date} {self.start_time}-{self.end_time} resource={self.resource_id}>"


# Import for type hints
from app.models.organisation import Resource  # noqa: E402
from app.models.member import User  # noqa: E402
