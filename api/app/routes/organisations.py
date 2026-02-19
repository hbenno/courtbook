"""Organisation, site, and resource routes."""

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import require_org_admin
from app.models.member import OrgMembership
from app.models.organisation import Organisation, Resource, Site
from app.schemas import OrgMembershipOut, OrganisationOut, ResourceOut, SiteOut

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
        select(Site)
        .join(Organisation)
        .where(Organisation.slug == slug, Site.is_active.is_(True))
        .order_by(Site.name)
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
    result = await db.execute(
        select(Organisation).where(Organisation.slug == slug, Organisation.is_active.is_(True))
    )
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
