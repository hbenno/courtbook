"""Organisation, site, and resource routes."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import require_org_admin
from app.models.booking import Booking, BookingStatus
from app.models.member import OrgMembership
from app.models.organisation import Organisation, Resource, Site
from app.schemas import AvailabilityOut, OrganisationOut, OrgMembershipOut, ResourceOut, SiteOut, SlotOut
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
