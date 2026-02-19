"""User booking preferences for the Phase 4 fairness allocation window.

Each user can have multiple preference entries per org, ordered by priority.
The solver tries priority 1 first, cascades to 2, 3, etc.
"""

from datetime import time
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.member import User
    from app.models.organisation import Organisation, Resource, Site


class UserPreference(TimestampMixin, Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id"), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)

    # Where — both optional for flexible preferences
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"))
    resource_id: Mapped[int | None] = mapped_column(ForeignKey("resources.id"))

    # When — all optional
    day_of_week: Mapped[int | None] = mapped_column(Integer)  # 0=Mon..6=Sun
    preferred_start_time: Mapped[time | None] = mapped_column(Time)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship(lazy="raise")
    organisation: Mapped["Organisation"] = relationship(lazy="raise")
    site: Mapped["Site | None"] = relationship(lazy="raise")
    resource: Mapped["Resource | None"] = relationship(lazy="raise")

    __table_args__ = (
        Index("ix_prefs_user_org", "user_id", "organisation_id"),
        Index("ix_prefs_user_org_priority", "user_id", "organisation_id", "priority", unique=True),
    )

    def __repr__(self) -> str:
        return f"<UserPreference user={self.user_id} org={self.organisation_id} priority={self.priority}>"
