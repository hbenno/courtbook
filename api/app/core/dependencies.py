"""FastAPI dependencies for injection into route handlers."""

from collections.abc import Callable

from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import decode_token
from app.core.database import get_db
from app.models.member import OrgMembership, OrgRole, User, UserRole
from app.models.organisation import Organisation

bearer_scheme = HTTPBearer(auto_error=False)


def _is_platform_admin(user: User) -> bool:
    """Check if user has platform-level admin privileges."""
    return user.role in (UserRole.ADMIN, UserRole.SUPERADMIN)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate the current user from the JWT bearer token."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Require the current user to be a platform admin or superadmin."""
    if not _is_platform_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


# ---------------------------------------------------------------------------
# Org-level RBAC
# ---------------------------------------------------------------------------

async def get_org_membership(
    slug: str = Path(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrgMembership:
    """Resolve the authenticated user's membership within the org identified by URL slug.

    Platform admins bypass the membership check — if they have no OrgMembership
    record, a query is still attempted but the 403 is suppressed so they can
    access any org's admin endpoints.

    Returns the OrgMembership with tier eagerly loaded.
    """
    # Resolve the org from the slug
    result = await db.execute(
        select(Organisation).where(Organisation.slug == slug, Organisation.is_active.is_(True))
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found")

    # Look up membership
    result = await db.execute(
        select(OrgMembership)
        .options(selectinload(OrgMembership.tier))
        .where(
            OrgMembership.user_id == user.id,
            OrgMembership.organisation_id == org.id,
            OrgMembership.is_active.is_(True),
        )
    )
    membership = result.scalar_one_or_none()

    if membership is None:
        # Platform admins can access any org even without a membership record
        if _is_platform_admin(user):
            return None  # type: ignore[return-value]
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organisation",
        )

    return membership


def require_org_role(*allowed_roles: OrgRole) -> Callable:
    """Factory: return a dependency that enforces the user has one of the allowed org roles.

    Platform admins always pass regardless of their org role.

    Usage in a route:
        @router.get("/orgs/{slug}/admin-thing")
        async def admin_thing(membership=Depends(require_org_role(OrgRole.ADMIN))):
            ...
    """
    async def _check(
        membership: OrgMembership | None = Depends(get_org_membership),
        user: User = Depends(get_current_user),
    ) -> OrgMembership | None:
        # Platform admins bypass role checks
        if _is_platform_admin(user):
            return membership

        # membership is guaranteed non-None here (get_org_membership raises 403 for non-admins)
        if membership.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of: {', '.join(r.value for r in allowed_roles)}",
            )
        return membership

    return _check


# Convenience shortcuts
require_org_admin = require_org_role(OrgRole.ADMIN)
require_org_coach = require_org_role(OrgRole.ADMIN, OrgRole.COACH)
require_org_member = get_org_membership  # any active membership suffices
