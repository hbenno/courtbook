"""Seed the database with Hackney Tennis test data.

Run with: python -m scripts.seed
Creates the organisation, all 7 parks with courts, membership tiers, and test users.
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import hash_password
from app.core.database import async_session_factory, engine
from app.models import Base, MembershipTier, OrgMembership, Organisation, Resource, Site, User, UserRole, OrgRole


# Hackney Tennis parks and courts
# All courts are hard surface.
# Floodlights only at Clissold Park (courts 2-7) and Hackney Downs (courts 3-4).
PARKS = [
    {
        "name": "Clissold Park",
        "slug": "clissold-park",
        "postcode": "N16 9HJ",
        "latitude": 51.5610,
        "longitude": -0.0802,
        "courts": [
            {"name": "Court 1", "surface": "hard", "has_floodlights": False},
            {"name": "Court 2", "surface": "hard", "has_floodlights": True},
            {"name": "Court 3", "surface": "hard", "has_floodlights": True},
            {"name": "Court 4", "surface": "hard", "has_floodlights": True},
            {"name": "Court 5", "surface": "hard", "has_floodlights": True},
            {"name": "Court 6", "surface": "hard", "has_floodlights": True},
            {"name": "Court 7", "surface": "hard", "has_floodlights": True},
            {"name": "Court 8", "surface": "hard", "has_floodlights": False},
            {"name": "Mini Court 1", "surface": "hard", "has_floodlights": False, "resource_type": "mini_court"},
            {"name": "Mini Court 2", "surface": "hard", "has_floodlights": False, "resource_type": "mini_court"},
        ],
    },
    {
        "name": "Hackney Downs",
        "slug": "hackney-downs",
        "postcode": "E5 8ND",
        "latitude": 51.5530,
        "longitude": -0.0560,
        "courts": [
            {"name": "Court 1", "surface": "hard", "has_floodlights": False},
            {"name": "Court 2", "surface": "hard", "has_floodlights": False},
            {"name": "Court 3", "surface": "hard", "has_floodlights": True},
            {"name": "Court 4", "surface": "hard", "has_floodlights": True},
            # Court 5 exists but is turn-up-and-play only (not bookable through platform)
            {"name": "Court 5 (Turn Up & Play)", "surface": "hard", "has_floodlights": False, "is_bookable": False},
        ],
    },
    {
        "name": "Millfields Park",
        "slug": "millfields-park",
        "postcode": "E5 0AR",
        "latitude": 51.5540,
        "longitude": -0.0440,
        "courts": [
            {"name": "Court 1", "surface": "hard", "has_floodlights": False},
            {"name": "Court 2", "surface": "hard", "has_floodlights": False},
            {"name": "Court 3", "surface": "hard", "has_floodlights": False},
            {"name": "Court 4", "surface": "hard", "has_floodlights": False},
        ],
    },
    {
        "name": "Spring Hill",
        "slug": "spring-hill",
        "postcode": "E5 9BL",
        "latitude": 51.5560,
        "longitude": -0.0510,
        "courts": [
            {"name": "Court 1", "surface": "hard", "has_floodlights": False},
            {"name": "Court 2", "surface": "hard", "has_floodlights": False},
            {"name": "Court 3", "surface": "hard", "has_floodlights": False},
        ],
    },
    {
        "name": "Springfield Park",
        "slug": "springfield-park",
        "postcode": "E5 9EF",
        "latitude": 51.5590,
        "longitude": -0.0470,
        "courts": [
            {"name": "Court 1", "surface": "hard", "has_floodlights": False},
            {"name": "Court 2", "surface": "hard", "has_floodlights": False},
            {"name": "Court 3", "surface": "hard", "has_floodlights": False},
            {"name": "Court 4", "surface": "hard", "has_floodlights": False},
            {"name": "Court 5", "surface": "hard", "has_floodlights": False},
        ],
    },
    {
        "name": "London Fields",
        "slug": "london-fields",
        "postcode": "E8 3EU",
        "latitude": 51.5413,
        "longitude": -0.0579,
        "courts": [
            {"name": "Court 1", "surface": "hard", "has_floodlights": False},
            {"name": "Court 2", "surface": "hard", "has_floodlights": False},
        ],
    },
    {
        "name": "Joe White Gardens",
        "slug": "joe-white-gardens",
        "postcode": "E8 1HH",
        "latitude": 51.5430,
        "longitude": -0.0630,
        "courts": [
            {"name": "Court 1", "surface": "hard", "has_floodlights": False},
        ],
    },
]

TIERS = [
    {
        "name": "Adult Member",
        "slug": "adult",
        "advance_booking_days": 7,
        "max_concurrent_bookings": 7,
        "max_daily_minutes": 120,
        "cancellation_deadline_hours": 24,
        "annual_fee_pence": 4500,
        "peak_booking_fee_pence": 0,
        "offpeak_booking_fee_pence": 0,
        "fairness_eligible": True,
        "sort_order": 0,
    },
    {
        "name": "Junior Member",
        "slug": "junior",
        "advance_booking_days": 7,
        "max_concurrent_bookings": 7,
        "max_daily_minutes": 120,
        "cancellation_deadline_hours": 24,
        "annual_fee_pence": 1500,
        "peak_booking_fee_pence": 0,
        "offpeak_booking_fee_pence": 0,
        "fairness_eligible": True,
        "fairness_weight": 0.8,
        "sort_order": 1,
    },
    {
        "name": "Senior Member",
        "slug": "senior",
        "advance_booking_days": 7,
        "max_concurrent_bookings": 7,
        "max_daily_minutes": 120,
        "cancellation_deadline_hours": 24,
        "annual_fee_pence": 2500,
        "peak_booking_fee_pence": 0,
        "offpeak_booking_fee_pence": 0,
        "fairness_eligible": True,
        "sort_order": 2,
    },
    {
        "name": "Pay and Play",
        "slug": "pay-and-play",
        "advance_booking_days": 7,
        "max_concurrent_bookings": 7,
        "max_daily_minutes": 120,
        "cancellation_deadline_hours": 24,
        "annual_fee_pence": 0,
        "peak_booking_fee_pence": 900,
        "offpeak_booking_fee_pence": 600,
        "fairness_eligible": False,
        "sort_order": 3,
    },
    {
        "name": "Coach Level 2",
        "slug": "coach-l2",
        "advance_booking_days": 28,
        "max_concurrent_bookings": 999,
        "max_daily_minutes": 240,
        "cancellation_deadline_hours": 36,
        "annual_fee_pence": 0,
        "peak_booking_fee_pence": 0,
        "offpeak_booking_fee_pence": 0,
        "fairness_eligible": False,
        "sort_order": 4,
    },
    {
        "name": "Coach Level 3",
        "slug": "coach-l3",
        "advance_booking_days": 28,
        "max_concurrent_bookings": 999,
        "max_daily_minutes": 240,
        "cancellation_deadline_hours": 36,
        "annual_fee_pence": 0,
        "peak_booking_fee_pence": 0,
        "offpeak_booking_fee_pence": 0,
        "fairness_eligible": False,
        "sort_order": 5,
    },
    {
        "name": "Coach Level 4",
        "slug": "coach-l4",
        "advance_booking_days": 28,
        "max_concurrent_bookings": 999,
        "max_daily_minutes": 240,
        "cancellation_deadline_hours": 36,
        "annual_fee_pence": 0,
        "peak_booking_fee_pence": 0,
        "offpeak_booking_fee_pence": 0,
        "fairness_eligible": False,
        "sort_order": 6,
    },
    {
        "name": "Coach Level 5",
        "slug": "coach-l5",
        "advance_booking_days": 28,
        "max_concurrent_bookings": 999,
        "max_daily_minutes": 240,
        "cancellation_deadline_hours": 36,
        "annual_fee_pence": 0,
        "peak_booking_fee_pence": 0,
        "offpeak_booking_fee_pence": 0,
        "fairness_eligible": False,
        "sort_order": 7,
    },
]


async def seed():
    # Create tables (in dev; production uses Alembic migrations)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as db:
        # Check if already seeded
        result = await db.execute(select(Organisation).where(Organisation.slug == "hackney-tennis"))
        if result.scalar_one_or_none():
            print("Database already seeded — skipping.")
            return

        # Organisation
        org = Organisation(
            name="Hackney Tennis",
            slug="hackney-tennis",
            email="info@hackneytennis.org",
            website="https://www.hackneytennis.org",
        )
        db.add(org)
        await db.flush()

        # Sites and courts
        total_courts = 0
        total_mini = 0
        total_non_bookable = 0
        for park_data in PARKS:
            courts = park_data.pop("courts")
            site = Site(organisation_id=org.id, **park_data)
            db.add(site)
            await db.flush()

            for i, court_data in enumerate(courts):
                slug = court_data["name"].lower().replace(" ", "-").replace("(", "").replace(")", "").replace("&", "and")
                resource_type = court_data.pop("resource_type", "court")
                is_bookable = court_data.pop("is_bookable", True)

                resource = Resource(
                    site_id=site.id,
                    name=court_data["name"],
                    slug=slug,
                    resource_type=resource_type,
                    surface=court_data["surface"],
                    has_floodlights=court_data["has_floodlights"],
                    is_active=is_bookable,  # non-bookable courts marked inactive
                    sort_order=i,
                )
                db.add(resource)

                if resource_type == "mini_court":
                    total_mini += 1
                elif not is_bookable:
                    total_non_bookable += 1
                else:
                    total_courts += 1

        # Membership tiers
        tier_map = {}
        for tier_data in TIERS:
            tier = MembershipTier(organisation_id=org.id, **tier_data)
            db.add(tier)
            await db.flush()
            tier_map[tier.slug] = tier

        # Test users
        admin = User(
            email="admin@hackneytennis.org",
            hashed_password=hash_password("admin123"),
            first_name="Test",
            last_name="Admin",
            role=UserRole.ADMIN,
            email_verified=True,
        )
        db.add(admin)
        await db.flush()

        # Admin org membership
        db.add(OrgMembership(
            user_id=admin.id,
            organisation_id=org.id,
            tier_id=tier_map["adult"].id,
            role=OrgRole.ADMIN,
        ))

        member = User(
            email="member@example.com",
            hashed_password=hash_password("member123"),
            first_name="Test",
            last_name="Member",
            email_verified=True,
        )
        db.add(member)
        await db.flush()

        db.add(OrgMembership(
            user_id=member.id,
            organisation_id=org.id,
            tier_id=tier_map["adult"].id,
            role=OrgRole.MEMBER,
        ))

        await db.commit()

        print(f"Seeded: {org.name}")
        print(f"  {len(PARKS)} parks")
        print(f"  {total_courts} bookable courts")
        print(f"  {total_mini} mini courts")
        print(f"  {total_non_bookable} non-bookable (turn up & play)")
        print(f"  {len(TIERS)} membership tiers")
        print(f"  2 test users:")
        print(f"    admin@hackneytennis.org / admin123")
        print(f"    member@example.com / member123")


if __name__ == "__main__":
    asyncio.run(seed())
