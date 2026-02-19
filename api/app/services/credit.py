"""Credit service for managing booking credit balances.

Credit balance is cached on OrgMembership.credit_balance_pence for fast reads.
The authoritative audit trail is the credit_transactions table.
All mutations go through this service to keep the cache in sync.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credit import CreditTransaction, TransactionType
from app.models.member import OrgMembership


async def get_credit_balance(db: AsyncSession, user_id: int, org_id: int) -> int:
    """Read the cached credit balance in pence."""
    result = await db.execute(
        select(OrgMembership.credit_balance_pence).where(
            OrgMembership.user_id == user_id,
            OrgMembership.organisation_id == org_id,
            OrgMembership.is_active.is_(True),
        )
    )
    balance = result.scalar_one_or_none()
    return balance or 0


async def _apply(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    amount_pence: int,
    txn_type: TransactionType,
    booking_id: int | None,
    description: str,
) -> CreditTransaction:
    """Core credit mutation: adjust balance and record a transaction.

    Uses SELECT ... FOR UPDATE on the membership row to prevent race conditions.
    """
    mem_result = await db.execute(
        select(OrgMembership)
        .where(
            OrgMembership.user_id == user_id,
            OrgMembership.organisation_id == org_id,
            OrgMembership.is_active.is_(True),
        )
        .with_for_update()
    )
    membership = mem_result.scalar_one()

    new_balance = membership.credit_balance_pence + amount_pence
    membership.credit_balance_pence = new_balance

    txn = CreditTransaction(
        user_id=user_id,
        organisation_id=org_id,
        amount_pence=amount_pence,
        balance_after_pence=new_balance,
        transaction_type=txn_type,
        booking_id=booking_id,
        description=description,
    )
    db.add(txn)
    await db.flush()
    return txn


async def deduct_credit(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    amount_pence: int,
    booking_id: int,
) -> int:
    """Deduct up to amount_pence from the user's credit balance.

    Returns the amount actually deducted (may be less if balance is insufficient).
    """
    if amount_pence <= 0:
        return 0

    balance = await get_credit_balance(db, user_id, org_id)
    deduction = min(balance, amount_pence)
    if deduction <= 0:
        return 0

    await _apply(
        db,
        user_id,
        org_id,
        amount_pence=-deduction,
        txn_type=TransactionType.BOOKING_PAYMENT,
        booking_id=booking_id,
        description=f"Payment for booking #{booking_id}",
    )
    return deduction


async def grant_credit(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    amount_pence: int,
    description: str,
) -> CreditTransaction:
    """Grant credit to a user (admin action)."""
    return await _apply(
        db,
        user_id,
        org_id,
        amount_pence=amount_pence,
        txn_type=TransactionType.GRANT,
        booking_id=None,
        description=description,
    )


async def credit_cancellation(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    amount_pence: int,
    booking_id: int,
) -> CreditTransaction:
    """Credit the full booking amount back on cancellation."""
    return await _apply(
        db,
        user_id,
        org_id,
        amount_pence=amount_pence,
        txn_type=TransactionType.CANCELLATION_CREDIT,
        booking_id=booking_id,
        description=f"Cancellation credit for booking #{booking_id}",
    )


async def reverse_credit_deduction(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    booking_id: int,
) -> CreditTransaction | None:
    """Reverse a booking payment credit deduction (e.g. on Stripe payment failure).

    Finds the original BOOKING_PAYMENT transaction for this booking and reverses it.
    Returns None if no deduction was found to reverse.
    """
    txn_result = await db.execute(
        select(CreditTransaction).where(
            CreditTransaction.booking_id == booking_id,
            CreditTransaction.user_id == user_id,
            CreditTransaction.organisation_id == org_id,
            CreditTransaction.transaction_type == TransactionType.BOOKING_PAYMENT,
        )
    )
    original = txn_result.scalar_one_or_none()
    if original is None:
        return None

    # original.amount_pence is negative (debit), so negate to reverse
    return await _apply(
        db,
        user_id,
        org_id,
        amount_pence=-original.amount_pence,
        txn_type=TransactionType.PAYMENT_REVERSAL,
        booking_id=booking_id,
        description=f"Reversal of credit deduction for booking #{booking_id}",
    )
