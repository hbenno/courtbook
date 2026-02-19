"""Stripe integration service for payment processing.

Wraps the Stripe Python SDK. All amounts are in pence (GBP).
"""

import contextlib

import stripe
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.member import User


def _configure() -> None:
    """Set the Stripe API key from settings."""
    stripe.api_key = settings.stripe_secret_key


async def ensure_stripe_customer(user: User, db: AsyncSession) -> str:
    """Get or create a Stripe customer for the user.

    Stores the customer ID on the User model for future use.
    """
    _configure()

    if user.stripe_customer_id:
        return user.stripe_customer_id

    customer = stripe.Customer.create(
        email=user.email,
        name=user.full_name,
        metadata={"courtbook_user_id": str(user.id)},
    )
    user.stripe_customer_id = customer.id
    await db.flush()
    return customer.id


async def create_payment_intent(
    amount_pence: int,
    customer_id: str,
    booking_id: int,
    org_id: int,
) -> stripe.PaymentIntent:
    """Create a Stripe PaymentIntent for a booking payment.

    Returns the PaymentIntent object (caller reads .id and .client_secret).
    """
    _configure()

    return stripe.PaymentIntent.create(
        amount=amount_pence,
        currency="gbp",
        customer=customer_id,
        metadata={
            "booking_id": str(booking_id),
            "organisation_id": str(org_id),
        },
        automatic_payment_methods={"enabled": True},
    )


def cancel_payment_intent(payment_intent_id: str) -> None:
    """Cancel a pending PaymentIntent (e.g. on booking cancellation)."""
    _configure()

    with contextlib.suppress(stripe.StripeError):
        stripe.PaymentIntent.cancel(payment_intent_id)


def construct_webhook_event(payload: bytes, sig_header: str) -> stripe.Event:
    """Verify and construct a Stripe webhook event."""
    return stripe.Webhook.construct_event(
        payload,
        sig_header,
        settings.stripe_webhook_secret,
    )
