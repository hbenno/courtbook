"""Stripe webhook handler.

Processes payment_intent.succeeded and payment_intent.payment_failed events.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.booking import Booking, BookingStatus, PaymentStatus
from app.services.credit import reverse_credit_deduction
from app.services.stripe_service import construct_webhook_event

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events.

    Uses a dedicated DB session (not the request-scoped one) because webhook
    processing must commit independently of any ongoing request.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = construct_webhook_event(payload, sig_header)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature") from None

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "payment_intent.succeeded":
        await _handle_payment_succeeded(data)
    elif event_type == "payment_intent.payment_failed":
        await _handle_payment_failed(data)

    return {"status": "ok"}


async def _handle_payment_succeeded(payment_intent: dict) -> None:
    """Mark the booking as paid."""
    pi_id = payment_intent["id"]

    async with async_session_factory() as db:
        result = await db.execute(select(Booking).where(Booking.stripe_payment_intent_id == pi_id))
        booking = result.scalar_one_or_none()
        if booking is None:
            return  # Unknown PI — ignore

        booking.payment_status = PaymentStatus.PAID
        await db.commit()


async def _handle_payment_failed(payment_intent: dict) -> None:
    """Cancel the booking and reverse any credit deduction."""
    pi_id = payment_intent["id"]

    async with async_session_factory() as db:
        result = await db.execute(select(Booking).where(Booking.stripe_payment_intent_id == pi_id))
        booking = result.scalar_one_or_none()
        if booking is None:
            return

        # Cancel the booking
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = datetime.now(UTC)
        booking.payment_status = PaymentStatus.NOT_REQUIRED

        # Reverse any credit that was deducted for this booking
        await reverse_credit_deduction(db, booking.user_id, booking.organisation_id, booking.id)

        await db.commit()
