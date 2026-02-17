"""Booking routes: create, list, cancel.

Phase 0/1: FCFS only. Fairness window allocation added in Phase 4.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.booking import Booking, BookingStatus
from app.models.member import User
from app.schemas import BookingCreate, BookingOut

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
async def create_booking(
    body: BookingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Calculate end time
    start_dt = datetime.combine(body.booking_date, body.start_time)
    end_dt = start_dt + timedelta(minutes=body.duration_minutes)
    end_time = end_dt.time()

    # Check for conflicts (confirmed bookings on same resource at same time)
    conflict = await db.execute(
        select(Booking).where(
            Booking.resource_id == body.resource_id,
            Booking.booking_date == body.booking_date,
            Booking.status == BookingStatus.CONFIRMED,
            # Overlap: existing start < new end AND existing end > new start
            Booking.start_time < end_time,
            Booking.end_time > body.start_time,
        )
    )
    if conflict.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Court already booked for this time slot",
        )

    booking = Booking(
        organisation_id=1,  # TODO: resolve from resource -> site -> org
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
    result = await db.execute(
        select(Booking).where(Booking.id == booking_id, Booking.user_id == user.id)
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    if booking.status != BookingStatus.CONFIRMED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Booking cannot be cancelled")

    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = datetime.now(UTC)
