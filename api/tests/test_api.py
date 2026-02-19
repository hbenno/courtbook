"""API tests: health, auth, availability, preferences, password reset, pricing, credit, payment."""

import uuid
from datetime import date, time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.auth import create_password_reset_token, hash_password
from app.core.database import async_session_factory
from app.main import app
from app.models import Booking, BookingStatus, Organisation, Resource, Site, User
from app.models.credit import CreditTransaction
from app.models.member import MembershipTier, OrgMembership, OrgRole, UserRole
from app.models.preference import UserPreference
from app.services.operating_hours import closing_time, generate_slots
from app.services.pricing import (
    BAND_EARLY,
    BAND_FLOODLIGHT,
    BAND_OFFPEAK,
    BAND_PEAK,
    calculate_booking_fee,
    determine_price_band,
)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def seed_availability_data():
    """Create a minimal org + site + 2 courts for availability tests. Cleans bookings each run."""
    async with async_session_factory() as db:
        # Check if already created (idempotent for test reruns)
        result = await db.execute(select(Organisation).where(Organisation.slug == "test-org"))
        org = result.scalar_one_or_none()
        if org:
            courts_result = await db.execute(select(Resource).join(Site).where(Site.organisation_id == org.id))
            courts = {r.name: r for r in courts_result.scalars().all()}
            user_result = await db.execute(select(User).where(User.email == "avail-test@example.com"))
            user = user_result.scalar_one()
            # Clean up any bookings from previous runs
            await db.execute(delete(Booking).where(Booking.organisation_id == org.id))
            await db.commit()
            return {
                "org": org,
                "floodlit_court": courts["Floodlit Court"],
                "dark_court": courts["Dark Court"],
                "user": user,
            }

        org = Organisation(name="Test Org", slug="test-org", email="test@test.com")
        db.add(org)
        await db.flush()

        site = Site(organisation_id=org.id, name="Test Park", slug="test-park", postcode="E5 0AA")
        db.add(site)
        await db.flush()

        floodlit = Resource(
            site_id=site.id,
            name="Floodlit Court",
            slug="floodlit-court",
            surface="hard",
            has_floodlights=True,
            is_active=True,
            sort_order=0,
        )
        dark = Resource(
            site_id=site.id,
            name="Dark Court",
            slug="dark-court",
            surface="hard",
            has_floodlights=False,
            is_active=True,
            sort_order=1,
        )
        db.add_all([floodlit, dark])
        await db.flush()

        user = User(
            email="avail-test@example.com",
            hashed_password=hash_password("test123"),
            first_name="Avail",
            last_name="Tester",
        )
        db.add(user)
        await db.flush()

        await db.commit()
        return {
            "org": org,
            "floodlit_court": floodlit,
            "dark_court": dark,
            "user": user,
        }


# ---------------------------------------------------------------------------
# Original tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_register_and_login(client):
    email = f"test-{uuid.uuid4().hex[:8]}@example.com"

    # Register
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "testpass123",
            "first_name": "Test",
            "last_name": "User",
        },
    )
    assert resp.status_code == 201
    tokens = resp.json()
    assert "access_token" in tokens

    # Login
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": "testpass123",
        },
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()

    # Me (authenticated)
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == email


@pytest.mark.asyncio
async def test_me_unauthenticated(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Unit tests: operating_hours (pure functions, no DB)
# ---------------------------------------------------------------------------


class TestClosingTime:
    def test_floodlit_always_21(self):
        assert closing_time(has_floodlights=True, is_indoor=False, query_date=date(2026, 6, 15)) == time(21, 0)
        assert closing_time(has_floodlights=True, is_indoor=False, query_date=date(2026, 12, 15)) == time(21, 0)

    def test_indoor_always_21(self):
        assert closing_time(has_floodlights=False, is_indoor=True, query_date=date(2026, 12, 15)) == time(21, 0)

    def test_non_floodlit_winter_short_day(self):
        # Mid-December: London sunset ~15:50, floors to 15:00
        close = closing_time(has_floodlights=False, is_indoor=False, query_date=date(2026, 12, 15))
        assert close <= time(16, 0)
        assert close >= time(15, 0)

    def test_non_floodlit_summer_capped_at_21(self):
        # Late June: London sunset ~21:20, floors to 21:00, capped at 21:00
        close = closing_time(has_floodlights=False, is_indoor=False, query_date=date(2026, 6, 21))
        assert close == time(21, 0)

    def test_non_floodlit_uses_monday_of_week(self):
        # A Wednesday and the Monday of the same week should give the same closing time
        wednesday = date(2026, 3, 18)
        monday = date(2026, 3, 16)
        assert closing_time(False, False, wednesday) == closing_time(False, False, monday)

    def test_non_floodlit_spring_reasonable(self):
        # Late March: sunset ~18:20, floors to 18:00
        close = closing_time(has_floodlights=False, is_indoor=False, query_date=date(2026, 3, 23))
        assert time(17, 0) <= close <= time(19, 0)


class TestGenerateSlots:
    def test_floodlit_slot_count(self):
        # 07:00-21:00 = 14 one-hour slots
        future = date.today() + timedelta(days=30)
        slots = generate_slots(has_floodlights=True, is_indoor=False, query_date=future, booked_intervals=[])
        assert len(slots) == 14
        assert slots[0]["start_time"] == "07:00"
        assert slots[-1]["start_time"] == "20:00"
        assert slots[-1]["end_time"] == "21:00"

    def test_all_available_when_no_bookings(self):
        future = date.today() + timedelta(days=30)
        slots = generate_slots(True, False, future, [])
        assert all(s["is_available"] for s in slots)

    def test_60_min_booking_blocks_one_slot(self):
        future = date.today() + timedelta(days=30)
        booked = [(time(9, 0), time(10, 0))]
        slots = generate_slots(True, False, future, booked)
        slot_map = {s["start_time"]: s["is_available"] for s in slots}
        assert slot_map["09:00"] is False
        assert slot_map["08:00"] is True
        assert slot_map["10:00"] is True

    def test_120_min_booking_blocks_two_slots(self):
        future = date.today() + timedelta(days=30)
        booked = [(time(9, 0), time(11, 0))]  # 2-hour booking
        slots = generate_slots(True, False, future, booked)
        slot_map = {s["start_time"]: s["is_available"] for s in slots}
        assert slot_map["09:00"] is False
        assert slot_map["10:00"] is False
        assert slot_map["08:00"] is True
        assert slot_map["11:00"] is True

    def test_past_slots_unavailable(self):
        yesterday = date.today() - timedelta(days=1)
        slots = generate_slots(True, False, yesterday, [])
        assert all(not s["is_available"] for s in slots)

    def test_non_floodlit_winter_fewer_slots(self):
        # December: closing ~15:00, so 07:00-14:00 = 8 slots
        future_dec = date(2026, 12, 14)  # A Monday
        slots = generate_slots(False, False, future_dec, [])
        assert len(slots) < 14
        assert len(slots) >= 7  # At minimum 07:00-13:00 even in deep winter


# ---------------------------------------------------------------------------
# Integration tests: availability endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_availability_floodlit_no_bookings(client, seed_availability_data):
    data = seed_availability_data
    court_id = data["floodlit_court"].id
    future = (date.today() + timedelta(days=30)).isoformat()

    resp = await client.get(f"/api/v1/orgs/test-org/sites/test-park/courts/{court_id}/availability?date={future}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["court_id"] == court_id
    assert body["court_name"] == "Floodlit Court"
    assert body["date"] == future
    assert len(body["slots"]) == 14
    assert all(s["is_available"] for s in body["slots"])


@pytest.mark.asyncio
async def test_availability_with_booking(client, seed_availability_data):
    data = seed_availability_data
    court = data["floodlit_court"]
    user = data["user"]
    future = date.today() + timedelta(days=30)

    async with async_session_factory() as db:
        booking = Booking(
            organisation_id=data["org"].id,
            resource_id=court.id,
            user_id=user.id,
            booking_date=future,
            start_time=time(9, 0),
            end_time=time(10, 0),
            duration_minutes=60,
            status=BookingStatus.CONFIRMED,
        )
        db.add(booking)
        await db.commit()

    url = f"/api/v1/orgs/test-org/sites/test-park/courts/{court.id}/availability?date={future.isoformat()}"
    resp = await client.get(url)
    assert resp.status_code == 200
    slot_map = {s["start_time"]: s["is_available"] for s in resp.json()["slots"]}
    assert slot_map["09:00"] is False
    assert slot_map["08:00"] is True
    assert slot_map["10:00"] is True


@pytest.mark.asyncio
async def test_availability_120min_booking_blocks_two_slots(client, seed_availability_data):
    data = seed_availability_data
    court = data["floodlit_court"]
    user = data["user"]
    future = date.today() + timedelta(days=31)

    async with async_session_factory() as db:
        booking = Booking(
            organisation_id=data["org"].id,
            resource_id=court.id,
            user_id=user.id,
            booking_date=future,
            start_time=time(14, 0),
            end_time=time(16, 0),
            duration_minutes=120,
            status=BookingStatus.CONFIRMED,
        )
        db.add(booking)
        await db.commit()

    url = f"/api/v1/orgs/test-org/sites/test-park/courts/{court.id}/availability?date={future.isoformat()}"
    resp = await client.get(url)
    assert resp.status_code == 200
    slot_map = {s["start_time"]: s["is_available"] for s in resp.json()["slots"]}
    assert slot_map["14:00"] is False
    assert slot_map["15:00"] is False
    assert slot_map["13:00"] is True
    assert slot_map["16:00"] is True


@pytest.mark.asyncio
async def test_availability_404_nonexistent_court(client, seed_availability_data):
    future = (date.today() + timedelta(days=30)).isoformat()
    resp = await client.get(f"/api/v1/orgs/test-org/sites/test-park/courts/99999/availability?date={future}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_availability_404_wrong_site(client, seed_availability_data):
    court_id = seed_availability_data["floodlit_court"].id
    future = (date.today() + timedelta(days=30)).isoformat()
    resp = await client.get(f"/api/v1/orgs/test-org/sites/wrong-park/courts/{court_id}/availability?date={future}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_availability_non_floodlit_winter(client, seed_availability_data):
    court_id = seed_availability_data["dark_court"].id
    # Use a December date — fewer slots than floodlit
    resp = await client.get(f"/api/v1/orgs/test-org/sites/test-park/courts/{court_id}/availability?date=2026-12-14")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["slots"]) < 14  # Shorter day than floodlit
    assert body["slots"][0]["start_time"] == "07:00"


# ---------------------------------------------------------------------------
# Preferences tests
# ---------------------------------------------------------------------------

PREF_USER_EMAIL = "pref-test@example.com"
PREF_USER_PASSWORD = "preftest123"


@pytest.fixture
async def seed_pref_data():
    """Create org, site, 2 courts, membership tier, user with membership. Cleans preferences each run."""
    async with async_session_factory() as db:
        org_result = await db.execute(select(Organisation).where(Organisation.slug == "pref-org"))
        org = org_result.scalar_one_or_none()
        if org:
            # Clean preferences from previous runs
            await db.execute(delete(UserPreference).where(UserPreference.organisation_id == org.id))
            await db.commit()

            site_result = await db.execute(select(Site).where(Site.organisation_id == org.id))
            site = site_result.scalar_one()
            courts_result = await db.execute(select(Resource).where(Resource.site_id == site.id))
            courts = {r.name: r for r in courts_result.scalars().all()}
            user_result = await db.execute(select(User).where(User.email == PREF_USER_EMAIL))
            user = user_result.scalar_one()
            return {
                "org": org,
                "site": site,
                "court_a": courts["Court A"],
                "court_b": courts["Court B"],
                "user": user,
            }

        org = Organisation(name="Pref Org", slug="pref-org", email="pref@test.com")
        db.add(org)
        await db.flush()

        site = Site(organisation_id=org.id, name="Pref Park", slug="pref-park", postcode="E5 0AA")
        db.add(site)
        await db.flush()

        court_a = Resource(
            site_id=site.id,
            name="Court A",
            slug="court-a",
            surface="hard",
            has_floodlights=True,
            is_active=True,
            sort_order=0,
        )
        court_b = Resource(
            site_id=site.id,
            name="Court B",
            slug="court-b",
            surface="hard",
            has_floodlights=False,
            is_active=True,
            sort_order=1,
        )
        db.add_all([court_a, court_b])
        await db.flush()

        tier = MembershipTier(
            organisation_id=org.id,
            name="Adult",
            slug="adult",
            advance_booking_days=7,
            max_concurrent_bookings=7,
            max_daily_minutes=120,
            cancellation_deadline_hours=24,
        )
        db.add(tier)
        await db.flush()

        user = User(
            email=PREF_USER_EMAIL,
            hashed_password=hash_password(PREF_USER_PASSWORD),
            first_name="Pref",
            last_name="Tester",
        )
        db.add(user)
        await db.flush()

        membership = OrgMembership(
            user_id=user.id,
            organisation_id=org.id,
            tier_id=tier.id,
        )
        db.add(membership)
        await db.commit()

        return {
            "org": org,
            "site": site,
            "court_a": court_a,
            "court_b": court_b,
            "user": user,
        }


@pytest.fixture
async def pref_auth_headers(client, seed_pref_data):
    """Login as the pref test user and return auth headers."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": PREF_USER_EMAIL, "password": PREF_USER_PASSWORD},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_preferences_get_empty(client, seed_pref_data, pref_auth_headers):
    resp = await client.get("/api/v1/orgs/pref-org/preferences", headers=pref_auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_preferences_put_valid(client, seed_pref_data, pref_auth_headers):
    data = seed_pref_data
    body = {
        "preferences": [
            {"site_id": data["site"].id, "day_of_week": 0, "preferred_start_time": "19:00", "duration_minutes": 60},
            {"site_id": data["site"].id, "resource_id": data["court_a"].id, "day_of_week": 2, "duration_minutes": 120},
        ]
    }
    resp = await client.put("/api/v1/orgs/pref-org/preferences", headers=pref_auth_headers, json=body)
    assert resp.status_code == 200
    result = resp.json()
    assert len(result) == 2
    assert result[0]["priority"] == 1
    assert result[0]["site_name"] == "Pref Park"
    assert result[0]["resource_id"] is None
    assert result[0]["resource_name"] is None
    assert result[0]["day_of_week"] == 0
    assert result[0]["duration_minutes"] == 60
    assert result[1]["priority"] == 2
    assert result[1]["resource_name"] == "Court A"
    assert result[1]["duration_minutes"] == 120


@pytest.mark.asyncio
async def test_preferences_put_replaces_existing(client, seed_pref_data, pref_auth_headers):
    data = seed_pref_data
    # Set initial preferences
    body1 = {"preferences": [{"site_id": data["site"].id, "duration_minutes": 60}]}
    resp = await client.put("/api/v1/orgs/pref-org/preferences", headers=pref_auth_headers, json=body1)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # Replace with different preferences
    body2 = {
        "preferences": [
            {"site_id": data["site"].id, "resource_id": data["court_b"].id, "duration_minutes": 120},
            {"site_id": data["site"].id, "day_of_week": 5, "duration_minutes": 60},
        ]
    }
    resp = await client.put("/api/v1/orgs/pref-org/preferences", headers=pref_auth_headers, json=body2)
    assert resp.status_code == 200
    result = resp.json()
    assert len(result) == 2
    assert result[0]["priority"] == 1
    assert result[0]["resource_name"] == "Court B"
    assert result[1]["priority"] == 2
    assert result[1]["day_of_week"] == 5


@pytest.mark.asyncio
async def test_preferences_delete(client, seed_pref_data, pref_auth_headers):
    data = seed_pref_data
    # Create some preferences first
    body = {"preferences": [{"site_id": data["site"].id, "duration_minutes": 60}]}
    await client.put("/api/v1/orgs/pref-org/preferences", headers=pref_auth_headers, json=body)

    # Delete
    resp = await client.delete("/api/v1/orgs/pref-org/preferences", headers=pref_auth_headers)
    assert resp.status_code == 204

    # Confirm empty
    resp = await client.get("/api/v1/orgs/pref-org/preferences", headers=pref_auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_preferences_invalid_site(client, seed_pref_data, pref_auth_headers):
    body = {"preferences": [{"site_id": 99999, "duration_minutes": 60}]}
    resp = await client.put("/api/v1/orgs/pref-org/preferences", headers=pref_auth_headers, json=body)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_preferences_invalid_resource(client, seed_pref_data, pref_auth_headers):
    data = seed_pref_data
    body = {"preferences": [{"site_id": data["site"].id, "resource_id": 99999, "duration_minutes": 60}]}
    resp = await client.put("/api/v1/orgs/pref-org/preferences", headers=pref_auth_headers, json=body)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_preferences_resource_wrong_site(client, seed_pref_data, pref_auth_headers):
    """resource_id from another org is rejected."""
    body = {"preferences": [{"resource_id": 99999, "duration_minutes": 60}]}
    resp = await client.put("/api/v1/orgs/pref-org/preferences", headers=pref_auth_headers, json=body)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_preferences_invalid_day_of_week(client, seed_pref_data, pref_auth_headers):
    data = seed_pref_data
    body = {"preferences": [{"site_id": data["site"].id, "day_of_week": 7, "duration_minutes": 60}]}
    resp = await client.put("/api/v1/orgs/pref-org/preferences", headers=pref_auth_headers, json=body)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_preferences_invalid_duration(client, seed_pref_data, pref_auth_headers):
    data = seed_pref_data
    body = {"preferences": [{"site_id": data["site"].id, "duration_minutes": 90}]}
    resp = await client.put("/api/v1/orgs/pref-org/preferences", headers=pref_auth_headers, json=body)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_preferences_too_many(client, seed_pref_data, pref_auth_headers):
    data = seed_pref_data
    body = {"preferences": [{"site_id": data["site"].id, "duration_minutes": 60}] * 11}
    resp = await client.put("/api/v1/orgs/pref-org/preferences", headers=pref_auth_headers, json=body)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_preferences_unauthenticated(client, seed_pref_data):
    resp = await client.get("/api/v1/orgs/pref-org/preferences")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_preferences_non_member(client, seed_pref_data):
    """A user who is not a member of the org gets 403."""
    email = f"nonmember-{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "test123", "first_name": "Non", "last_name": "Member"},
    )
    assert resp.status_code == 201
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/api/v1/orgs/pref-org/preferences", headers=headers)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Password reset tests
# ---------------------------------------------------------------------------

RESET_USER_EMAIL = "reset-test@example.com"
RESET_USER_PASSWORD = "oldpass123"


@pytest.fixture
async def seed_reset_user():
    """Create a user for password reset tests."""
    async with async_session_factory() as db:
        user_result = await db.execute(select(User).where(User.email == RESET_USER_EMAIL))
        user = user_result.scalar_one_or_none()
        if user:
            # Reset password back to original for test idempotency
            user.hashed_password = hash_password(RESET_USER_PASSWORD)
            await db.commit()
            return user

        user = User(
            email=RESET_USER_EMAIL,
            hashed_password=hash_password(RESET_USER_PASSWORD),
            first_name="Reset",
            last_name="Tester",
        )
        db.add(user)
        await db.commit()
        return user


@pytest.mark.asyncio
@patch("app.routes.auth.send_password_reset_email", new_callable=AsyncMock)
async def test_forgot_password_valid_email(mock_send, client, seed_reset_user):
    resp = await client.post("/api/v1/auth/forgot-password", json={"email": RESET_USER_EMAIL})
    assert resp.status_code == 200
    assert "reset link" in resp.json()["message"].lower()
    mock_send.assert_called_once()
    assert mock_send.call_args[0][0] == RESET_USER_EMAIL


@pytest.mark.asyncio
@patch("app.routes.auth.send_password_reset_email", new_callable=AsyncMock)
async def test_forgot_password_unknown_email(mock_send, client):
    resp = await client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
    assert resp.status_code == 200  # No user enumeration
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_reset_password_valid_token(client, seed_reset_user):
    user = seed_reset_user
    token = create_password_reset_token(user.id, user.hashed_password)

    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "newpass456"},
    )
    assert resp.status_code == 200
    assert "successfully" in resp.json()["message"].lower()

    # Can login with new password
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": RESET_USER_EMAIL, "password": "newpass456"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()

    # Old password no longer works
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": RESET_USER_EMAIL, "password": RESET_USER_PASSWORD},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_reset_password_token_already_used(client, seed_reset_user):
    """After using a token to reset, the same token should be rejected (fingerprint mismatch)."""
    user = seed_reset_user
    token = create_password_reset_token(user.id, user.hashed_password)

    # Use the token
    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "newpass789"},
    )
    assert resp.status_code == 200

    # Try to use the same token again
    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "anotherpass"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_reset_password_tampered_token(client, seed_reset_user):
    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": "totally.invalid.token", "new_password": "newpass123"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_reset_password_missing_fields(client):
    resp = await client.post("/api/v1/auth/reset-password", json={"token": "abc"})
    assert resp.status_code == 422

    resp = await client.post("/api/v1/auth/reset-password", json={"new_password": "abc"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Pricing unit tests (pure functions, no DB)
# ---------------------------------------------------------------------------


def _resource(floodlit=False):
    return SimpleNamespace(has_floodlights=floodlit)


def _tier(**overrides):
    defaults = {
        "early_booking_fee_pence": 390,
        "offpeak_booking_fee_pence": 525,
        "peak_booking_fee_pence": 800,
        "floodlight_booking_fee_pence": 1360,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestPriceBand:
    def test_weekday_early(self):
        # Monday 8am → early
        assert determine_price_band(_resource(), date(2026, 3, 16), time(8, 0), time(9, 0)) == BAND_EARLY

    def test_weekday_offpeak(self):
        # Monday 12pm → offpeak
        assert determine_price_band(_resource(), date(2026, 3, 16), time(12, 0), time(13, 0)) == BAND_OFFPEAK

    def test_weekday_peak(self):
        # Monday 7pm → peak
        assert determine_price_band(_resource(), date(2026, 3, 16), time(19, 0), time(20, 0)) == BAND_PEAK

    def test_weekend_early(self):
        # Saturday 8am → early
        assert determine_price_band(_resource(), date(2026, 3, 21), time(8, 0), time(9, 0)) == BAND_EARLY

    def test_weekend_peak(self):
        # Saturday 10am → peak
        assert determine_price_band(_resource(), date(2026, 3, 21), time(10, 0), time(11, 0)) == BAND_PEAK

    def test_floodlight_winter(self):
        # December Monday, floodlit court, 5pm-6pm (sunset ~3pm) → floodlight
        assert (
            determine_price_band(_resource(floodlit=True), date(2026, 12, 14), time(17, 0), time(18, 0))
            == BAND_FLOODLIGHT
        )

    def test_non_floodlit_no_floodlight_band(self):
        # Non-floodlit court after dusk → normal band (offpeak at 5pm weekday)
        assert determine_price_band(_resource(), date(2026, 12, 14), time(17, 0), time(18, 0)) == BAND_OFFPEAK

    def test_floodlit_summer_before_dusk(self):
        # June floodlit court, 3pm-4pm (dusk ~9pm) → offpeak not floodlight
        band = determine_price_band(_resource(floodlit=True), date(2026, 6, 15), time(15, 0), time(16, 0))
        assert band == BAND_OFFPEAK

    def test_custom_org_config(self):
        # Override weekend early end to 10am → 9am is still early
        config = {"weekend_early_end": "10:00"}
        assert determine_price_band(_resource(), date(2026, 3, 21), time(9, 0), time(10, 0), config) == BAND_EARLY


class TestBookingFee:
    def test_early_1hr(self):
        fee, band = calculate_booking_fee(_tier(), _resource(), date(2026, 3, 16), time(8, 0), 60)
        assert fee == 390
        assert band == BAND_EARLY

    def test_offpeak_1hr(self):
        fee, band = calculate_booking_fee(_tier(), _resource(), date(2026, 3, 16), time(12, 0), 60)
        assert fee == 525
        assert band == BAND_OFFPEAK

    def test_peak_1hr(self):
        fee, band = calculate_booking_fee(_tier(), _resource(), date(2026, 3, 16), time(19, 0), 60)
        assert fee == 800
        assert band == BAND_PEAK

    def test_peak_2hr_doubles(self):
        fee, band = calculate_booking_fee(_tier(), _resource(), date(2026, 3, 16), time(19, 0), 120)
        assert fee == 1600
        assert band == BAND_PEAK

    def test_floodlight(self):
        fee, band = calculate_booking_fee(_tier(), _resource(floodlit=True), date(2026, 12, 14), time(17, 0), 60)
        assert fee == 1360
        assert band == BAND_FLOODLIGHT

    def test_junior_reduced_peak(self):
        junior = _tier(peak_booking_fee_pence=390)
        fee, band = calculate_booking_fee(junior, _resource(), date(2026, 3, 21), time(10, 0), 60)
        assert fee == 390
        assert band == BAND_PEAK

    def test_zero_fee_tier(self):
        free_tier = _tier(
            early_booking_fee_pence=0,
            offpeak_booking_fee_pence=0,
            peak_booking_fee_pence=0,
            floodlight_booking_fee_pence=0,
        )
        fee, band = calculate_booking_fee(free_tier, _resource(), date(2026, 3, 16), time(12, 0), 60)
        assert fee == 0


# ---------------------------------------------------------------------------
# Payment / Credit integration tests
# ---------------------------------------------------------------------------

PAYMENT_USER_EMAIL = "payment-test@example.com"
PAYMENT_USER_PASSWORD = "payment123"
PAYMENT_ADMIN_EMAIL = "payment-admin@example.com"
PAYMENT_ADMIN_PASSWORD = "payadmin123"


def _next_weekday(days_ahead: int = 3) -> date:
    """Return a future weekday date for booking tests."""
    d = date.today() + timedelta(days=days_ahead)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


@pytest.fixture
async def seed_payment_data():
    """Create org, site, courts, tier, users for payment flow tests."""
    async with async_session_factory() as db:
        org_result = await db.execute(select(Organisation).where(Organisation.slug == "pay-org"))
        org = org_result.scalar_one_or_none()
        if org:
            # Clean up from previous runs
            await db.execute(delete(CreditTransaction).where(CreditTransaction.organisation_id == org.id))
            await db.execute(delete(Booking).where(Booking.organisation_id == org.id))
            mem_result = await db.execute(select(OrgMembership).where(OrgMembership.organisation_id == org.id))
            for m in mem_result.scalars().all():
                m.credit_balance_pence = 0
            await db.commit()

            site_result = await db.execute(select(Site).where(Site.organisation_id == org.id))
            site = site_result.scalar_one()
            courts_result = await db.execute(select(Resource).where(Resource.site_id == site.id))
            courts = {r.name: r for r in courts_result.scalars().all()}
            user_result = await db.execute(select(User).where(User.email == PAYMENT_USER_EMAIL))
            user = user_result.scalar_one()
            admin_result = await db.execute(select(User).where(User.email == PAYMENT_ADMIN_EMAIL))
            admin = admin_result.scalar_one()
            tier_result = await db.execute(
                select(MembershipTier).where(
                    MembershipTier.organisation_id == org.id, MembershipTier.slug == "test-adult"
                )
            )
            tier = tier_result.scalar_one()
            mem_result2 = await db.execute(
                select(OrgMembership).where(OrgMembership.user_id == user.id, OrgMembership.organisation_id == org.id)
            )
            membership = mem_result2.scalar_one()
            return {
                "org": org,
                "site": site,
                "court": courts["Pay Court"],
                "floodlit_court": courts["Pay Floodlit"],
                "tier": tier,
                "user": user,
                "admin": admin,
                "membership": membership,
            }

        org = Organisation(name="Pay Org", slug="pay-org", email="pay@test.com")
        db.add(org)
        await db.flush()

        site = Site(organisation_id=org.id, name="Pay Park", slug="pay-park", postcode="E5 0AA")
        db.add(site)
        await db.flush()

        court = Resource(
            site_id=site.id,
            name="Pay Court",
            slug="pay-court",
            surface="hard",
            has_floodlights=False,
            is_active=True,
            sort_order=0,
        )
        floodlit = Resource(
            site_id=site.id,
            name="Pay Floodlit",
            slug="pay-floodlit",
            surface="hard",
            has_floodlights=True,
            is_active=True,
            sort_order=1,
        )
        db.add_all([court, floodlit])
        await db.flush()

        # Tier with uniform 500p fee for all bands (isolates payment logic from band logic)
        tier = MembershipTier(
            organisation_id=org.id,
            name="Test Adult",
            slug="test-adult",
            advance_booking_days=7,
            max_concurrent_bookings=7,
            max_daily_minutes=240,
            cancellation_deadline_hours=0,  # Allow immediate cancellation in tests
            early_booking_fee_pence=500,
            offpeak_booking_fee_pence=500,
            peak_booking_fee_pence=500,
            floodlight_booking_fee_pence=500,
        )
        db.add(tier)
        await db.flush()

        user = User(
            email=PAYMENT_USER_EMAIL,
            hashed_password=hash_password(PAYMENT_USER_PASSWORD),
            first_name="Pay",
            last_name="Tester",
        )
        db.add(user)
        await db.flush()

        membership = OrgMembership(
            user_id=user.id,
            organisation_id=org.id,
            tier_id=tier.id,
            role=OrgRole.MEMBER,
        )
        db.add(membership)

        admin = User(
            email=PAYMENT_ADMIN_EMAIL,
            hashed_password=hash_password(PAYMENT_ADMIN_PASSWORD),
            first_name="Pay",
            last_name="Admin",
            role=UserRole.ADMIN,
        )
        db.add(admin)
        await db.flush()

        admin_membership = OrgMembership(
            user_id=admin.id,
            organisation_id=org.id,
            tier_id=tier.id,
            role=OrgRole.ADMIN,
        )
        db.add(admin_membership)
        await db.commit()

        return {
            "org": org,
            "site": site,
            "court": court,
            "floodlit_court": floodlit,
            "tier": tier,
            "user": user,
            "admin": admin,
            "membership": membership,
        }


@pytest.fixture
async def pay_auth_headers(client, seed_payment_data):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": PAYMENT_USER_EMAIL, "password": PAYMENT_USER_PASSWORD},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def pay_admin_headers(client, seed_payment_data):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": PAYMENT_ADMIN_EMAIL, "password": PAYMENT_ADMIN_PASSWORD},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _booking_body(court_id: int, start_hour: int = 12) -> dict:
    """Build a valid booking request body."""
    return {
        "resource_id": court_id,
        "booking_date": _next_weekday().isoformat(),
        "start_time": f"{start_hour:02d}:00",
        "duration_minutes": 60,
    }


@pytest.mark.asyncio
async def test_booking_with_full_credit(client, seed_payment_data, pay_auth_headers):
    """When credit covers the full fee, no Stripe is needed."""
    data = seed_payment_data
    # Grant 1000p credit (fee will be 500p)
    async with async_session_factory() as db:
        from app.services.credit import grant_credit

        await grant_credit(db, data["user"].id, data["org"].id, 1000, "Test grant")
        await db.commit()

    resp = await client.post(
        "/api/v1/bookings",
        headers=pay_auth_headers,
        json=_booking_body(data["court"].id),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["amount_pence"] == 500
    assert body["payment_status"] == "paid"
    assert body["client_secret"] is None


@pytest.mark.asyncio
@patch("app.routes.bookings.ensure_stripe_customer", new_callable=AsyncMock, return_value="cus_test123")
@patch("app.routes.bookings.create_payment_intent", new_callable=AsyncMock)
async def test_booking_no_credit_full_stripe(
    mock_create_pi,
    mock_customer,
    client,
    seed_payment_data,
    pay_auth_headers,
):
    """When no credit, full amount goes to Stripe."""
    mock_pi = MagicMock()
    mock_pi.id = "pi_test123"
    mock_pi.client_secret = "secret_test123"
    mock_create_pi.return_value = mock_pi

    data = seed_payment_data
    resp = await client.post(
        "/api/v1/bookings",
        headers=pay_auth_headers,
        json=_booking_body(data["court"].id, start_hour=13),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["amount_pence"] == 500
    assert body["payment_status"] == "pending"
    assert body["client_secret"] == "secret_test123"

    mock_create_pi.assert_called_once()
    assert mock_create_pi.call_args[0][0] == 500  # Full amount


@pytest.mark.asyncio
@patch("app.routes.bookings.ensure_stripe_customer", new_callable=AsyncMock, return_value="cus_test123")
@patch("app.routes.bookings.create_payment_intent", new_callable=AsyncMock)
async def test_booking_partial_credit(mock_create_pi, mock_customer, client, seed_payment_data, pay_auth_headers):
    """When credit only partially covers fee, Stripe handles the remainder."""
    mock_pi = MagicMock()
    mock_pi.id = "pi_partial"
    mock_pi.client_secret = "secret_partial"
    mock_create_pi.return_value = mock_pi

    data = seed_payment_data
    # Grant 200p credit (fee is 500p, so 300p goes to Stripe)
    async with async_session_factory() as db:
        from app.services.credit import grant_credit

        await grant_credit(db, data["user"].id, data["org"].id, 200, "Partial credit")
        await db.commit()

    resp = await client.post(
        "/api/v1/bookings",
        headers=pay_auth_headers,
        json=_booking_body(data["court"].id, start_hour=14),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["amount_pence"] == 500
    assert body["payment_status"] == "pending"
    assert body["client_secret"] == "secret_partial"

    # Stripe should be charged the remainder (500 - 200 = 300)
    mock_create_pi.assert_called_once()
    assert mock_create_pi.call_args[0][0] == 300


@pytest.mark.asyncio
async def test_cancel_booking_credits_back(client, seed_payment_data, pay_auth_headers):
    """Cancelling a paid booking credits the full amount back."""
    data = seed_payment_data
    # Grant credit and create a booking
    async with async_session_factory() as db:
        from app.services.credit import grant_credit

        await grant_credit(db, data["user"].id, data["org"].id, 1000, "For cancel test")
        await db.commit()

    resp = await client.post(
        "/api/v1/bookings",
        headers=pay_auth_headers,
        json=_booking_body(data["court"].id, start_hour=15),
    )
    assert resp.status_code == 201
    booking_id = resp.json()["id"]

    # Cancel it
    resp = await client.delete(f"/api/v1/bookings/{booking_id}", headers=pay_auth_headers)
    assert resp.status_code == 204

    # Check credit balance: started with 1000, paid 500, got 500 back = 1000
    async with async_session_factory() as db:
        from app.services.credit import get_credit_balance

        balance = await get_credit_balance(db, data["user"].id, data["org"].id)
        assert balance == 1000


@pytest.mark.asyncio
async def test_webhook_payment_succeeded(client, seed_payment_data):
    """Stripe webhook marks booking as paid."""
    data = seed_payment_data

    # Create a booking with pending payment directly in DB
    async with async_session_factory() as db:
        from app.models.booking import PaymentStatus

        booking = Booking(
            organisation_id=data["org"].id,
            resource_id=data["court"].id,
            user_id=data["user"].id,
            booking_date=_next_weekday(5),
            start_time=time(10, 0),
            end_time=time(11, 0),
            duration_minutes=60,
            amount_pence=500,
            payment_status=PaymentStatus.PENDING,
            stripe_payment_intent_id="pi_webhook_success",
        )
        db.add(booking)
        await db.commit()
        booking_id = booking.id

    event = {
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": "pi_webhook_success"}},
    }
    with patch("app.routes.webhooks.construct_webhook_event", return_value=event):
        resp = await client.post(
            "/api/v1/webhooks/stripe",
            content=b"payload",
            headers={"stripe-signature": "sig"},
        )
    assert resp.status_code == 200

    # Verify booking is now paid
    async with async_session_factory() as db:
        result = await db.execute(select(Booking).where(Booking.id == booking_id))
        booking = result.scalar_one()
        assert booking.payment_status == PaymentStatus.PAID


@pytest.mark.asyncio
async def test_webhook_payment_failed_reverses_credit(client, seed_payment_data):
    """Stripe payment failure cancels booking and reverses credit deduction."""
    data = seed_payment_data

    # Grant credit, create booking with credit deduction, simulate pending Stripe
    async with async_session_factory() as db:
        from app.models.booking import PaymentStatus
        from app.services.credit import grant_credit

        await grant_credit(db, data["user"].id, data["org"].id, 200, "For webhook fail test")

        booking = Booking(
            organisation_id=data["org"].id,
            resource_id=data["court"].id,
            user_id=data["user"].id,
            booking_date=_next_weekday(6),
            start_time=time(11, 0),
            end_time=time(12, 0),
            duration_minutes=60,
            amount_pence=500,
            payment_status=PaymentStatus.PENDING,
            stripe_payment_intent_id="pi_webhook_fail",
        )
        db.add(booking)
        await db.flush()

        # Simulate credit deduction that happened at booking time
        from app.services.credit import deduct_credit

        await deduct_credit(db, data["user"].id, data["org"].id, 200, booking.id)
        await db.commit()
        booking_id = booking.id

    event = {
        "type": "payment_intent.payment_failed",
        "data": {"object": {"id": "pi_webhook_fail"}},
    }
    with patch("app.routes.webhooks.construct_webhook_event", return_value=event):
        resp = await client.post(
            "/api/v1/webhooks/stripe",
            content=b"payload",
            headers={"stripe-signature": "sig"},
        )
    assert resp.status_code == 200

    # Verify booking is cancelled and credit was reversed
    async with async_session_factory() as db:
        result = await db.execute(select(Booking).where(Booking.id == booking_id))
        booking = result.scalar_one()
        assert booking.status == BookingStatus.CANCELLED

        from app.services.credit import get_credit_balance

        balance = await get_credit_balance(db, data["user"].id, data["org"].id)
        assert balance == 200  # Original 200 restored


@pytest.mark.asyncio
async def test_admin_grant_credit(client, seed_payment_data, pay_admin_headers):
    """Admin can grant credit to a member."""
    data = seed_payment_data
    member_id = data["membership"].id

    resp = await client.post(
        f"/api/v1/orgs/pay-org/members/{member_id}/credit",
        headers=pay_admin_headers,
        json={"amount_pence": 2000, "description": "Coach credit top-up"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["amount_pence"] == 2000
    assert body["transaction_type"] == "grant"
    assert body["balance_after_pence"] == 2000


@pytest.mark.asyncio
async def test_admin_get_credit_balance(client, seed_payment_data, pay_admin_headers):
    """Admin can view a member's credit balance."""
    data = seed_payment_data
    member_id = data["membership"].id

    resp = await client.get(
        f"/api/v1/orgs/pay-org/members/{member_id}/credit",
        headers=pay_admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == data["user"].id
    assert "balance_pence" in body
