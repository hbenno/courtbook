"""User booking preferences: GET, PUT (bulk replace), DELETE."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_org_membership
from app.models.member import OrgMembership, User
from app.models.organisation import Resource, Site
from app.models.preference import UserPreference
from app.schemas import PreferenceOut, PreferencesReplace

router = APIRouter(prefix="/orgs/{slug}/preferences", tags=["preferences"])

MAX_PREFERENCES = 10


def _build_preference_out(pref: UserPreference) -> PreferenceOut:
    return PreferenceOut(
        id=pref.id,
        priority=pref.priority,
        site_id=pref.site_id,
        site_name=pref.site.name if pref.site else None,
        resource_id=pref.resource_id,
        resource_name=pref.resource.name if pref.resource else None,
        day_of_week=pref.day_of_week,
        preferred_start_time=pref.preferred_start_time,
        duration_minutes=pref.duration_minutes,
    )


@router.get("", response_model=list[PreferenceOut])
async def get_preferences(
    membership: OrgMembership | None = Depends(get_org_membership),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = membership.organisation_id if membership else None
    if org_id is None:
        return []

    pref_result = await db.execute(
        select(UserPreference)
        .options(selectinload(UserPreference.site), selectinload(UserPreference.resource))
        .where(UserPreference.user_id == user.id, UserPreference.organisation_id == org_id)
        .order_by(UserPreference.priority)
    )
    prefs = pref_result.scalars().all()
    return [_build_preference_out(p) for p in prefs]


@router.put("", response_model=list[PreferenceOut])
async def replace_preferences(
    body: PreferencesReplace,
    membership: OrgMembership | None = Depends(get_org_membership),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = membership.organisation_id if membership else None
    if org_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation membership required")

    if len(body.preferences) > MAX_PREFERENCES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Maximum {MAX_PREFERENCES} preferences allowed",
        )

    # Pre-fetch all sites and resources for this org to validate FKs
    sites_result = await db.execute(select(Site).where(Site.organisation_id == org_id, Site.is_active.is_(True)))
    org_sites = {s.id: s for s in sites_result.scalars().all()}

    resources_result = await db.execute(
        select(Resource).join(Site).where(Site.organisation_id == org_id, Resource.is_active.is_(True))
    )
    org_resources = {r.id: r for r in resources_result.scalars().all()}

    # Validate each entry
    errors = []
    for i, pref in enumerate(body.preferences):
        if pref.site_id is not None and pref.site_id not in org_sites:
            errors.append(f"preferences[{i}]: site_id {pref.site_id} not found in this organisation")
        if pref.resource_id is not None:
            resource = org_resources.get(pref.resource_id)
            if resource is None:
                errors.append(f"preferences[{i}]: resource_id {pref.resource_id} not found in this organisation")
            elif pref.site_id is not None and resource.site_id != pref.site_id:
                errors.append(
                    f"preferences[{i}]: resource_id {pref.resource_id} does not belong to site_id {pref.site_id}"
                )
        if pref.day_of_week is not None and not (0 <= pref.day_of_week <= 6):
            errors.append(f"preferences[{i}]: day_of_week must be 0-6, got {pref.day_of_week}")
        if pref.duration_minutes not in (60, 120):
            errors.append(f"preferences[{i}]: duration_minutes must be 60 or 120, got {pref.duration_minutes}")

    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=errors)

    # Delete existing and insert new
    await db.execute(
        delete(UserPreference).where(
            UserPreference.user_id == user.id,
            UserPreference.organisation_id == org_id,
        )
    )

    new_prefs = []
    for i, pref in enumerate(body.preferences):
        new_pref = UserPreference(
            user_id=user.id,
            organisation_id=org_id,
            priority=i + 1,
            site_id=pref.site_id,
            resource_id=pref.resource_id,
            day_of_week=pref.day_of_week,
            preferred_start_time=pref.preferred_start_time,
            duration_minutes=pref.duration_minutes,
        )
        db.add(new_pref)
        new_prefs.append(new_pref)

    await db.flush()

    # Re-query with relationships loaded for the response
    pref_result = await db.execute(
        select(UserPreference)
        .options(selectinload(UserPreference.site), selectinload(UserPreference.resource))
        .where(UserPreference.user_id == user.id, UserPreference.organisation_id == org_id)
        .order_by(UserPreference.priority)
    )
    saved = pref_result.scalars().all()
    return [_build_preference_out(p) for p in saved]


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preferences(
    membership: OrgMembership | None = Depends(get_org_membership),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = membership.organisation_id if membership else None
    if org_id is None:
        return

    await db.execute(
        delete(UserPreference).where(
            UserPreference.user_id == user.id,
            UserPreference.organisation_id == org_id,
        )
    )
