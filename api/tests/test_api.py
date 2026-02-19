"""API tests: health, auth, availability, preferences, password reset."""

import uuid
from datetime import date, time, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.auth import create_password_reset_token, hash_password
from app.core.database import async_session_factory
from app.main import app
from app.models import Booking, BookingStatus, Organisation, Resource, Site, User
from app.models.member import MembershipTier, OrgMembership
from app.models.preference import UserPreference
from app.services.operating_hours import closing_time, generate_slots


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
