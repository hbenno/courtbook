"""Booking rules enforcement.

All booking validation logic lives here, separate from the route handlers.
Each rule returns a clear error message or None if the rule passes.
The main validate() function runs all rules and collects violations.
"""

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking, BookingStatus
from app.models.member import MembershipTier, OrgMembership


class BookingViolation(Exception):
    """Raised when a booking rule is violated."""

    def __init__(self, rule: str, message: str):
        self.rule = rule
        self.message = message
        super().__init__(message)


def _fmt_duration(minutes: int) -> str:
    """Format minutes as hours when evenly divisible by 60, otherwise minutes.

    120 -> "2 hours", 60 -> "1 hour", 90 -> "90 minutes", 0 -> "0 minutes"
    """
    if minutes == 0:
        return "0 minutes"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{minutes} minutes"


async def validate_booking(
    db: AsyncSession,
    user_id: int,
    org_membership: OrgMembership,
    resource_id: int,
    booking_date: date,
    start_time: time,
    duration_minutes: int,
) -> list[BookingViolation]:
    """Run all booking rules and return a list of violations (empty = valid)."""
    tier = org_membership.tier
    violations: list[BookingViolation] = []

    # 1. Slot duration
    v = check_slot_duration(tier, duration_minutes)
    if v:
        violations.append(v)

    # 2. Advance booking window
    v = check_advance_window(tier, booking_date)
    if v:
        violations.append(v)

    # 3. Not in the past
    v = check_not_in_past(booking_date, start_time)
    if v:
        violations.append(v)

    # 4. Max concurrent bookings (future confirmed bookings)
    v = await check_max_concurrent(db, user_id, tier)
    if v:
        violations.append(v)

    # 5. Max daily minutes
    v = await check_max_daily_minutes(db, user_id, tier, booking_date, duration_minutes)
    if v:
        violations.append(v)

    # 6. Court conflict (double booking)
    end_time = calc_end_time(start_time, duration_minutes)
    v = await check_court_conflict(db, resource_id, booking_date, start_time, end_time)
    if v:
        violations.append(v)

    return violations


def check_slot_duration(tier: MembershipTier, duration_minutes: int) -> BookingViolation | None:
    """Booking duration must be in the tier's allowed list."""
    allowed = tier.slot_durations_minutes or [60, 120]
    if duration_minutes not in allowed:
        return BookingViolation(
            "slot_duration",
            f"Duration {_fmt_duration(duration_minutes)} not allowed. Choose from: {', '.join(_fmt_duration(d) for d in allowed)}.",
        )
    return None


def check_advance_window(tier: MembershipTier, booking_date: date) -> BookingViolation | None:
    """Booking must be within the advance window, calculated from the window open time (default 9pm).

    Example: if today is Sunday and advance_booking_days=7, the window opens at 9pm tonight
    for next Sunday. Before 9pm, the furthest you can book is Saturday.
    """
    now = datetime.now(UTC)
    today = now.date()

    # Parse window time (e.g. "21:00")
    window_time_str = getattr(tier, "booking_window_time", "21:00") or "21:00"
    h, m = map(int, window_time_str.split(":"))
    window_time_today = datetime(today.year, today.month, today.day, h, m, tzinfo=UTC)

    # If we're past the window time, the window for advance_booking_days from now is open
    # If we're before the window time, it hasn't opened yet — so max date is one day less
    if now >= window_time_today:
        max_date = today + timedelta(days=tier.advance_booking_days)
    else:
        max_date = today + timedelta(days=tier.advance_booking_days - 1)

    if booking_date > max_date:
        return BookingViolation(
            "advance_window",
            f"Cannot book more than {tier.advance_booking_days} days in advance. "
            f"Earliest you can book {booking_date} is after {window_time_str} on {booking_date - timedelta(days=tier.advance_booking_days)}.",
        )

    return None


def check_not_in_past(booking_date: date, start_time: time) -> BookingViolation | None:
    """Cannot book a slot that has already started."""
    now = datetime.now(UTC)
    slot_start = datetime.combine(booking_date, start_time, tzinfo=UTC)

    if slot_start <= now:
        return BookingViolation("past_booking", "Cannot book a slot in the past.")

    return None


async def check_max_concurrent(
    db: AsyncSession, user_id: int, tier: MembershipTier
) -> BookingViolation | None:
    """Cannot exceed max concurrent confirmed future bookings."""
    now = datetime.now(UTC)
    today = now.date()

    result = await db.execute(
        select(func.count(Booking.id)).where(
            Booking.user_id == user_id,
            Booking.status == BookingStatus.CONFIRMED,
            Booking.booking_date >= today,
        )
    )
    count = result.scalar_one()

    if count >= tier.max_concurrent_bookings:
        return BookingViolation(
            "max_concurrent",
            f"You already have {count} upcoming bookings. Maximum allowed: {tier.max_concurrent_bookings}.",
        )

    return None


async def check_max_daily_minutes(
    db: AsyncSession,
    user_id: int,
    tier: MembershipTier,
    booking_date: date,
    duration_minutes: int,
) -> BookingViolation | None:
    """Cannot exceed max daily minutes on the same day."""
    result = await db.execute(
        select(func.coalesce(func.sum(Booking.duration_minutes), 0)).where(
            Booking.user_id == user_id,
            Booking.booking_date == booking_date,
            Booking.status == BookingStatus.CONFIRMED,
        )
    )
    booked_minutes = result.scalar_one()

    if booked_minutes + duration_minutes > tier.max_daily_minutes:
        remaining = tier.max_daily_minutes - booked_minutes
        return BookingViolation(
            "max_daily_minutes",
            f"You have {_fmt_duration(booked_minutes)} booked on {booking_date}. "
            f"Adding {_fmt_duration(duration_minutes)} would exceed your daily limit of {_fmt_duration(tier.max_daily_minutes)}. "
            f"You have {_fmt_duration(remaining)} remaining.",
        )

    return None


async def check_court_conflict(
    db: AsyncSession,
    resource_id: int,
    booking_date: date,
    start_time: time,
    end_time: time,
) -> BookingViolation | None:
    """No two confirmed bookings can overlap on the same court."""
    result = await db.execute(
        select(Booking).where(
            Booking.resource_id == resource_id,
            Booking.booking_date == booking_date,
            Booking.status == BookingStatus.CONFIRMED,
            Booking.start_time < end_time,
            Booking.end_time > start_time,
        )
    )
    conflict = result.scalar_one_or_none()

    if conflict:
        return BookingViolation(
            "court_conflict",
            f"Court already booked from {conflict.start_time.strftime('%H:%M')} to {conflict.end_time.strftime('%H:%M')}.",
        )

    return None


def validate_cancellation(booking: Booking, tier: MembershipTier) -> BookingViolation | None:
    """Check if a booking can still be cancelled within the deadline."""
    now = datetime.now(UTC)
    slot_start = datetime.combine(booking.booking_date, booking.start_time, tzinfo=UTC)
    deadline = slot_start - timedelta(hours=tier.cancellation_deadline_hours)

    if now > deadline:
        return BookingViolation(
            "cancellation_deadline",
            f"Cancellation deadline was {tier.cancellation_deadline_hours} hours before the booking "
            f"({deadline.strftime('%A %d %B at %H:%M')}). Too late to cancel.",
        )

    return None


def calc_end_time(start_time: time, duration_minutes: int) -> time:
    """Calculate end time from start time and duration."""
    start_dt = datetime.combine(date.today(), start_time)
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    return end_dt.time()
