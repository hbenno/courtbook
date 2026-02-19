"""Organisation and site models.

Organisation = a tennis charity/club (e.g. Hackney Tennis).
Site = a physical location with courts (e.g. London Fields, Clissold Park).
Resource = an individual bookable court at a site.
"""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.member import MembershipTier


class Organisation(TimestampMixin, Base):
    __tablename__ = "organisations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Contact / branding
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(50))
    website: Mapped[str | None] = mapped_column(String(500))
    logo_url: Mapped[str | None] = mapped_column(String(500))

    # Stripe Connect (populated in Phase 3+)
    stripe_account_id: Mapped[str | None] = mapped_column(String(100))

    # Flexible config (booking rules defaults, branding, etc.)
    config: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Relationships
    sites: Mapped[list["Site"]] = relationship(back_populates="organisation", lazy="selectin")
    membership_tiers: Mapped[list["MembershipTier"]] = relationship(back_populates="organisation", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Organisation {self.slug}>"


class Site(TimestampMixin, Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Location
    address: Mapped[str | None] = mapped_column(Text)
    postcode: Mapped[str | None] = mapped_column(String(20))
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7))

    # Site-level config overrides (booking rules, time bands, etc.)
    config: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Relationships
    organisation: Mapped["Organisation"] = relationship(back_populates="sites")
    resources: Mapped[list["Resource"]] = relationship(back_populates="site", lazy="selectin")

    __table_args__ = (Index("ix_sites_org_slug", "organisation_id", "slug", unique=True),)

    def __repr__(self) -> str:
        return f"<Site {self.slug} @ {self.organisation_id}>"


class Resource(TimestampMixin, Base):
    """A bookable resource — typically a tennis court, but could be a hall or room."""

    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), default="court", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Court-specific
    surface: Mapped[str | None] = mapped_column(String(50))  # hard, clay, grass, artificial
    is_indoor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_floodlights: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Display ordering
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)

    # Per-resource config overrides
    config: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Relationships
    site: Mapped["Site"] = relationship(back_populates="resources")

    __table_args__ = (Index("ix_resources_site_slug", "site_id", "slug", unique=True),)

    def __repr__(self) -> str:
        return f"<Resource {self.name} @ site {self.site_id}>"
