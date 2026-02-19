"""Member and membership models.

User = a person with login credentials (global, can belong to multiple orgs).
MembershipTier = a tier within an organisation (e.g. Adult, Junior, Senior).
OrgMembership = the link between a user and an organisation with their tier.
"""

import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class UserRole(enum.StrEnum):
    """Global platform roles."""

    MEMBER = "member"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class OrgRole(enum.StrEnum):
    """Roles within an organisation."""

    MEMBER = "member"
    COACH = "coach"
    ADMIN = "admin"
    TREASURER = "treasurer"


class User(TimestampMixin, Base):
    """A person who can log in. Global identity, not tied to one org."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda e: [x.value for x in e]),
        default=UserRole.MEMBER,
        nullable=False,
    )

    # Profile
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    date_of_birth: Mapped[date | None] = mapped_column(Date)

    # Migration tracking
    migrated_from: Mapped[str | None] = mapped_column(String(50))  # e.g. "clubspark"
    migrated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legacy_id: Mapped[str | None] = mapped_column(String(100))

    # GDPR
    marketing_consent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    contact_preferences: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Stripe customer (for card payments)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(100))

    # Relationships
    org_memberships: Mapped[list["OrgMembership"]] = relationship(back_populates="user", lazy="selectin")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class MembershipTier(TimestampMixin, Base):
    """A membership tier within an organisation (e.g. Adult, Junior, Senior, Pay-and-Play)."""

    __tablename__ = "membership_tiers"

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)

    # Booking rules for this tier
    advance_booking_days: Mapped[int] = mapped_column(default=7, nullable=False)
    max_concurrent_bookings: Mapped[int] = mapped_column(default=7, nullable=False)
    max_daily_minutes: Mapped[int] = mapped_column(default=120, nullable=False)  # max minutes per day
    cancellation_deadline_hours: Mapped[int] = mapped_column(default=24, nullable=False)
    slot_durations_minutes: Mapped[list] = mapped_column(JSONB, default=[60, 120])
    booking_window_time: Mapped[str] = mapped_column(String(5), default="21:00", nullable=False)  # HH:MM

    # Pricing (pennies to avoid float issues)
    annual_fee_pence: Mapped[int] = mapped_column(default=0, nullable=False)
    peak_booking_fee_pence: Mapped[int] = mapped_column(default=0, nullable=False)
    offpeak_booking_fee_pence: Mapped[int] = mapped_column(default=0, nullable=False)

    # Fairness window eligibility
    fairness_eligible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fairness_weight: Mapped[float] = mapped_column(default=1.0, nullable=False)

    # Relationships
    organisation: Mapped["Organisation"] = relationship(back_populates="membership_tiers")

    __table_args__ = (Index("ix_tiers_org_slug", "organisation_id", "slug", unique=True),)

    def __repr__(self) -> str:
        return f"<MembershipTier {self.name} @ org {self.organisation_id}>"


# Import here to avoid circular - Organisation is defined in organisation.py
from app.models.organisation import Organisation  # noqa: E402


class OrgMembership(TimestampMixin, Base):
    """Links a user to an organisation with a specific tier and role."""

    __tablename__ = "org_memberships"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id"), nullable=False)
    tier_id: Mapped[int] = mapped_column(ForeignKey("membership_tiers.id"), nullable=False)
    role: Mapped[OrgRole] = mapped_column(
        Enum(OrgRole, name="org_role", values_callable=lambda e: [x.value for x in e]),
        default=OrgRole.MEMBER,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Payment
    payment_method: Mapped[str | None] = mapped_column(String(50))  # stripe, gocardless, cash, free
    gocardless_mandate_id: Mapped[str | None] = mapped_column(String(100))

    # Relationships
    user: Mapped["User"] = relationship(back_populates="org_memberships")
    organisation: Mapped["Organisation"] = relationship()
    tier: Mapped["MembershipTier"] = relationship()

    __table_args__ = (Index("ix_orgmember_user_org", "user_id", "organisation_id", unique=True),)

    def __repr__(self) -> str:
        return f"<OrgMembership user={self.user_id} org={self.organisation_id}>"
