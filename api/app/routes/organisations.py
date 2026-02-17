"""Organisation, site, and resource routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.member import User
from app.models.organisation import Organisation, Resource, Site
from app.schemas import OrganisationOut, ResourceOut, SiteOut

router = APIRouter(prefix="/orgs", tags=["organisations"])


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
