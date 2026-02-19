"""Booking routes: create, list, cancel — with full rules enforcement and payment.

Phase 1: FCFS with pricing, credit, and Stripe payment.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.booking import Booking, BookingStatus, PaymentStatus
from app.models.member import OrgMembership, User
from app.models.organisation import Organisation, Resource
from app.schemas import BookingCreate, BookingOut
from app.services.booking_rules import calc_end_time, validate_booking, validate_cancellation
from app.services.credit import credit_cancellation, deduct_credit
from app.services.pricing import calculate_booking_fee
from app.services.stripe_service import cancel_payment_intent, create_payment_intent, ensure_stripe_customer

router = APIRouter(prefix="/bookings", tags=["bookings"])


async def _get_org_membership(
    db: AsyncSession, user_id: int, resource_id: int
) -> tuple[OrgMembership, Resource, Organisation]:
    """Resolve the user's org membership from the resource they're trying to book.

    Returns the OrgMembership (with tier loaded), the Resource, and the Organisation.
    """
    res_result = await db.execute(
        select(Resource)
        .options(selectinload(Resource.site))
        .where(Resource.id == resource_id, Resource.is_active.is_(True))
    )
    resource = res_result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Court not found or not bookable")

    org_id = resource.site.organisation_id

    # Load the organisation for config
    org_result = await db.execute(select(Organisation).where(Organisation.id == org_id))
    org = org_result.scalar_one()

    mem_result = await db.execute(
        select(OrgMembership)
        .options(selectinload(OrgMembership.tier))
        .where(
            OrgMembership.user_id == user_id,
            OrgMembership.organisation_id == org_id,
            OrgMembership.is_active.is_(True),
        )
    )
    membership = mem_result.scalar_one_or_none()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organisation",
        )

    return membership, resource, org


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
async def create_booking(
    body: BookingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    membership, resource, org = await _get_org_membership(db, user.id, body.resource_id)

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
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[{"rule": v.rule, "message": v.message} for v in violations],
        )

    end_time = calc_end_time(body.start_time, body.duration_minutes)

    # Calculate fee
    fee_pence, band = calculate_booking_fee(
        tier=membership.tier,
        resource=resource,
        booking_date=body.booking_date,
        start_time=body.start_time,
        duration_minutes=body.duration_minutes,
        org_config=org.config,
    )

    booking = Booking(
        organisation_id=org.id,
        resource_id=body.resource_id,
        user_id=user.id,
        booking_date=body.booking_date,
        start_time=body.start_time,
        end_time=end_time,
        duration_minutes=body.duration_minutes,
        amount_pence=fee_pence,
        extra={"price_band": band},
    )
    db.add(booking)
    await db.flush()

    client_secret = None

    if fee_pence == 0:
        # Free booking
        booking.payment_status = PaymentStatus.NOT_REQUIRED
    else:
        # Try credit deduction first
        credit_used = await deduct_credit(db, user.id, org.id, fee_pence, booking.id)
        remaining = fee_pence - credit_used

        if remaining == 0:
            # Fully covered by credit
            booking.payment_status = PaymentStatus.PAID
        else:
            # Need Stripe for the remainder
            customer_id = await ensure_stripe_customer(user, db)
            pi = await create_payment_intent(remaining, customer_id, booking.id, org.id)
            booking.stripe_payment_intent_id = pi.id
            booking.payment_status = PaymentStatus.PENDING
            client_secret = pi.client_secret

    await db.flush()

    # Build response — BookingOut doesn't have client_secret as a DB column,
    # so we construct it manually
    out = BookingOut.model_validate(booking)
    out.client_secret = client_secret
    return out


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
    result = await db.execute(select(Booking).where(Booking.id == booking_id, Booking.user_id == user.id))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    if booking.status != BookingStatus.CONFIRMED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Booking cannot be cancelled")

    # Get membership to check cancellation deadline
    membership, _, _ = await _get_org_membership(db, user.id, booking.resource_id)

    violation = validate_cancellation(booking, membership.tier)
    if violation:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[{"rule": violation.rule, "message": violation.message}],
        )

    # Cancel any pending Stripe PaymentIntent
    if booking.stripe_payment_intent_id and booking.payment_status == PaymentStatus.PENDING:
        cancel_payment_intent(booking.stripe_payment_intent_id)

    # Credit the full booking amount back (cancellations give credit, not refunds)
    if booking.amount_pence > 0:
        await credit_cancellation(db, user.id, booking.organisation_id, booking.amount_pence, booking.id)

    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = datetime.now(UTC)
