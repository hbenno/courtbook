"""Booking routes: create, list, cancel — with full rules enforcement.

Phase 0/1: FCFS only. Fairness window allocation added in Phase 4.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.booking import Booking, BookingStatus
from app.models.member import OrgMembership, User
from app.models.organisation import Resource, Site
from app.schemas import BookingCreate, BookingOut
from app.services.booking_rules import calc_end_time, validate_booking, validate_cancellation

router = APIRouter(prefix="/bookings", tags=["bookings"])


async def _get_org_membership(
    db: AsyncSession, user_id: int, resource_id: int
) -> tuple[OrgMembership, Resource]:
    """Resolve the user's org membership from the resource they're trying to book.

    Returns the OrgMembership (with tier loaded) and the Resource.
    Raises 404 if resource not found, 403 if user isn't a member of that org.
    """
    # Get resource -> site -> organisation
    result = await db.execute(
        select(Resource)
        .options(selectinload(Resource.site))
        .where(Resource.id == resource_id, Resource.is_active.is_(True))
    )
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Court not found or not bookable")

    org_id = resource.site.organisation_id

    # Get user's membership in this organisation (with tier loaded)
    result = await db.execute(
        select(OrgMembership)
        .options(selectinload(OrgMembership.tier))
        .where(
            OrgMembership.user_id == user_id,
            OrgMembership.organisation_id == org_id,
            OrgMembership.is_active.is_(True),
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organisation",
        )

    return membership, resource


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
async def create_booking(
    body: BookingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Resolve org membership and resource
    membership, resource = await _get_org_membership(db, user.id, body.resource_id)

    # Run all booking rules
    violations = await validate_booking(
        db=db,
        user_id=user.id,
        org_membership=membership,
        resource_id=body.resource_id,
        booking_date=body.booking_date,
        start_time=body.start_time,
        duration_minutes=body.duration_minutes,
    )

    if violations:
        # Return all violations so the user can fix them in one go
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[{"rule": v.rule, "message": v.message} for v in violations],
        )

    end_time = calc_end_time(body.start_time, body.duration_minutes)

    booking = Booking(
        organisation_id=resource.site.organisation_id,
        resource_id=body.resource_id,
        user_id=user.id,
        booking_date=body.booking_date,
        start_time=body.start_time,
        end_time=end_time,
        duration_minutes=body.duration_minutes,
    )
    db.add(booking)
    await db.flush()

    return booking


@router.get("", response_model=list[BookingOut])
async def list_my_bookings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Booking)
        .where(Booking.user_id == user.id)
        .order_by(Booking.booking_date.desc(), Booking.start_time.desc())
        .limit(50)
    )
    return result.scalars().all()


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_booking(
    booking_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Load booking
    result = await db.execute(
        select(Booking).where(Booking.id == booking_id, Booking.user_id == user.id)
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    if booking.status != BookingStatus.CONFIRMED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Booking cannot be cancelled")

    # Get membership to check cancellation deadline
    membership, _ = await _get_org_membership(db, user.id, booking.resource_id)

    violation = validate_cancellation(booking, membership.tier)
    if violation:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[{"rule": violation.rule, "message": violation.message}],
        )

    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = datetime.now(UTC)
