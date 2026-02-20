"""Organisation, site, and resource routes."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import require_org_admin
from app.models.booking import Booking, BookingStatus
from app.models.credit import CreditTransaction
from app.models.member import OrgMembership
from app.models.organisation import Organisation, Resource, Site
from app.schemas import (
    AvailabilityOut,
    CourtAvailability,
    CreditBalanceOut,
    CreditGrantRequest,
    CreditTransactionOut,
    OrganisationOut,
    OrgMembershipOut,
    ResourceOut,
    SiteAvailabilityOut,
    SiteOut,
    SlotOut,
)
from app.services.credit import get_credit_balance, grant_credit
from app.services.operating_hours import generate_slots

router = APIRouter(prefix="/orgs", tags=["organisations"])


# ---------------------------------------------------------------------------
# Public endpoints (no auth required — court availability for everyone)
# ---------------------------------------------------------------------------


@router.get("/{slug}", response_model=OrganisationOut)
async def get_organisation(slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Organisation).where(Organisation.slug == slug))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found")
    return org


@router.get("/{slug}/sites", response_model=list[SiteOut])
async def list_sites(slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Site).join(Organisation).where(Organisation.slug == slug, Site.is_active.is_(True)).order_by(Site.name)
    )
    return result.scalars().all()


@router.get("/{slug}/sites/{site_slug}/courts", response_model=list[ResourceOut])
async def list_courts(slug: str, site_slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Resource)
        .join(Site)
        .join(Organisation)
        .where(
            Organisation.slug == slug,
            Site.slug == site_slug,
            Resource.is_active.is_(True),
        )
        .order_by(Resource.sort_order, Resource.name)
    )
    return result.scalars().all()


@router.get(
    "/{slug}/sites/{site_slug}/availability",
    response_model=SiteAvailabilityOut,
)
async def get_site_availability(
    slug: str,
    site_slug: str,
    query_date: date = Query(..., alias="date", description="Date in YYYY-MM-DD format"),
    db: AsyncSession = Depends(get_db),
):
    """Return availability for ALL courts at a site on a given date.

    Used by the grid view where courts are columns and times are rows.
    """
    # Resolve the site
    site_result = await db.execute(
        select(Site)
        .join(Organisation)
        .where(
            Site.slug == site_slug,
            Site.is_active.is_(True),
            Organisation.slug == slug,
            Organisation.is_active.is_(True),
        )
    )
    site = site_result.scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")

    # Get all active courts at this site
    courts_result = await db.execute(
        select(Resource)
        .where(Resource.site_id == site.id, Resource.is_active.is_(True))
        .order_by(Resource.sort_order, Resource.name)
    )
    courts = courts_result.scalars().all()

    # Fetch all confirmed bookings for these courts on this date in one query
    court_ids = [c.id for c in courts]
    bookings_result = await db.execute(
        select(Booking.resource_id, Booking.start_time, Booking.end_time).where(
            Booking.resource_id.in_(court_ids),
            Booking.booking_date == query_date,
            Booking.status == BookingStatus.CONFIRMED,
        )
    )
    # Group bookings by court
    bookings_by_court: dict[int, list[tuple]] = {cid: [] for cid in court_ids}
    for row in bookings_result.all():
        bookings_by_court[row[0]].append((row[1], row[2]))

    court_avails = []
    for court in courts:
        slots = generate_slots(court.has_floodlights, court.is_indoor, query_date, bookings_by_court[court.id])
        court_avails.append(
            CourtAvailability(
                court_id=court.id,
                court_name=court.name,
                has_floodlights=court.has_floodlights,
                surface=court.surface,
                slots=[SlotOut(**s) for s in slots],
            )
        )

    return SiteAvailabilityOut(
        site_id=site.id,
        site_name=site.name,
        date=query_date,
        courts=court_avails,
    )


@router.get(
    "/{slug}/sites/{site_slug}/courts/{court_id}/availability",
    response_model=AvailabilityOut,
)
async def get_court_availability(
    slug: str,
    site_slug: str,
    court_id: int,
    query_date: date = Query(..., alias="date", description="Date in YYYY-MM-DD format"),
    db: AsyncSession = Depends(get_db),
):
    """Return all 60-minute slots for a court on a given date.

    Public endpoint — no auth required.
    Past slots are included with is_available=False so the frontend can
    render a complete day grid.
    """
    res_result = await db.execute(
        select(Resource)
        .join(Site)
        .join(Organisation)
        .where(
            Resource.id == court_id,
            Resource.is_active.is_(True),
            Site.slug == site_slug,
            Site.is_active.is_(True),
            Organisation.slug == slug,
            Organisation.is_active.is_(True),
        )
    )
    resource = res_result.scalar_one_or_none()
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Court not found")

    bookings_result = await db.execute(
        select(Booking.start_time, Booking.end_time).where(
            Booking.resource_id == court_id,
            Booking.booking_date == query_date,
            Booking.status == BookingStatus.CONFIRMED,
        )
    )
    booked_intervals = [(row[0], row[1]) for row in bookings_result.all()]

    slots = generate_slots(resource.has_floodlights, resource.is_indoor, query_date, booked_intervals)

    return AvailabilityOut(
        court_id=resource.id,
        court_name=resource.name,
        date=query_date,
        slots=[SlotOut(**s) for s in slots],
    )


# ---------------------------------------------------------------------------
# Admin endpoints (org admin or platform admin required)
# ---------------------------------------------------------------------------


@router.get("/{slug}/members", response_model=list[OrgMembershipOut])
async def list_members(
    slug: str = Path(...),
    membership: OrgMembership | None = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all members of the organisation. Requires org admin role."""
    result = await db.execute(select(Organisation).where(Organisation.slug == slug, Organisation.is_active.is_(True)))
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found")

    result = await db.execute(
        select(OrgMembership)
        .options(selectinload(OrgMembership.tier), selectinload(OrgMembership.user))
        .where(OrgMembership.organisation_id == org.id)
        .order_by(OrgMembership.id)
    )
    return result.scalars().all()


@router.get("/{slug}/members/{member_id}/credit", response_model=CreditBalanceOut)
async def get_member_credit(
    slug: str = Path(...),
    member_id: int = Path(...),
    membership: OrgMembership | None = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """View a member's credit balance. Requires org admin."""
    org_result = await db.execute(
        select(Organisation).where(Organisation.slug == slug, Organisation.is_active.is_(True))
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found")

    # Verify the member exists in this org
    mem_result = await db.execute(
        select(OrgMembership).where(OrgMembership.id == member_id, OrgMembership.organisation_id == org.id)
    )
    target = mem_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    balance = await get_credit_balance(db, target.user_id, org.id)
    return CreditBalanceOut(balance_pence=balance, user_id=target.user_id, organisation_id=org.id)


@router.get("/{slug}/members/{member_id}/credit/transactions", response_model=list[CreditTransactionOut])
async def list_member_transactions(
    slug: str = Path(...),
    member_id: int = Path(...),
    membership: OrgMembership | None = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """List recent credit transactions for a member. Requires org admin."""
    org_result = await db.execute(
        select(Organisation).where(Organisation.slug == slug, Organisation.is_active.is_(True))
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found")

    mem_result = await db.execute(
        select(OrgMembership).where(OrgMembership.id == member_id, OrgMembership.organisation_id == org.id)
    )
    target = mem_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    txn_result = await db.execute(
        select(CreditTransaction)
        .where(CreditTransaction.user_id == target.user_id, CreditTransaction.organisation_id == org.id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(50)
    )
    return txn_result.scalars().all()


@router.post(
    "/{slug}/members/{member_id}/credit",
    response_model=CreditTransactionOut,
    status_code=status.HTTP_201_CREATED,
)
async def grant_member_credit(
    body: CreditGrantRequest,
    slug: str = Path(...),
    member_id: int = Path(...),
    membership: OrgMembership | None = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """Grant credit to a member. Requires org admin."""
    org_result = await db.execute(
        select(Organisation).where(Organisation.slug == slug, Organisation.is_active.is_(True))
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found")

    mem_result = await db.execute(
        select(OrgMembership).where(OrgMembership.id == member_id, OrgMembership.organisation_id == org.id)
    )
    target = mem_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    if body.amount_pence <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount must be positive")

    txn = await grant_credit(db, target.user_id, org.id, body.amount_pence, body.description)
    return txn
