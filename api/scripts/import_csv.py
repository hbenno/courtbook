"""Import members and bookings from ClubSpark CSV exports.

Usage:
    python -m scripts.import_csv members data/members.csv [--dry-run]
    python -m scripts.import_csv bookings data/bookings.csv [--dry-run]

Column mappings are defined as dicts below — update them to match the actual
ClubSpark export headers once you have the real CSV files.
"""

import argparse
import asyncio
import contextlib
import csv
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.models.booking import Booking, BookingSource, BookingStatus, PaymentStatus
from app.models.member import MembershipTier, OrgMembership, OrgRole, User
from app.models.organisation import Organisation, Resource, Site

LONDON_TZ = ZoneInfo("Europe/London")

# ---------------------------------------------------------------------------
# Column mappings — matched to ClubSpark LTA CSV export format.
# Keys are internal field names, values are CSV column headers.
# NOTE: Verify exact headers by opening the real CSV in a text editor (not Excel)
# since Excel truncates long headers. These are best-effort from the test export.
# ---------------------------------------------------------------------------

MEMBER_COLUMNS = {
    "email": "Email",
    "first_name": "First name",
    "last_name": "Last Name",
    "phone": "Mobile number",
    "date_of_birth": "Date of Birth",
    "membership_type": "Membership",
    "member_id": "Venue ID",
    "expiry_date": "Expiry Date",
    # Also available but not mapped: Gender, Age, Junior, Payment,
    # Cost, Paid, Direct Debit, Address 1, Address 2, Emergency contact
}

BOOKING_COLUMNS = {
    "email": "Email",
    "venue": "Venue",
    "court": "Court",
    "date": "Date",
    "start_time": "Start Time",
    "end_time": "End Time",
    "duration_minutes": "Duration (mins)",
    "status": "Status",
    "amount_paid": "Amount Paid",
    "booking_id": "Booking ID",
}

# Map ClubSpark membership type names to CourtBook tier slugs.
# Keys are lowercased ClubSpark package names → CourtBook tier slugs.
# Add entries here as you discover what Hackney Tennis packages are called in ClubSpark.
TIER_MAP = {
    # Standard Hackney Tennis tiers
    "adult": "adult",
    "adult member": "adult",
    "adult membership": "adult",
    "junior": "junior",
    "junior member": "junior",
    "junior membership": "junior",
    "senior": "senior",
    "senior member": "senior",
    "senior membership": "senior",
    "pay and play": "pay-and-play",
    "pay & play": "pay-and-play",
    "coach level 2": "coach-l2",
    "coach level 3": "coach-l3",
    "coach level 4": "coach-l4",
    "coach level 5": "coach-l5",
    # ClubSpark test club tiers (seen in export) — remap or remove for production
    "friendly 2": "adult",
    "all test": "adult",
    "import": "adult",
    "additional": "adult",
}

# ClubSpark booking status → CourtBook BookingStatus
STATUS_MAP = {
    "confirmed": BookingStatus.CONFIRMED,
    "completed": BookingStatus.COMPLETED,
    "cancelled": BookingStatus.CANCELLED,
    "canceled": BookingStatus.CANCELLED,
    "no show": BookingStatus.NO_SHOW,
    "no_show": BookingStatus.NO_SHOW,
}

# Slugs that indicate a coach role
COACH_TIER_SLUGS = {"coach-l2", "coach-l3", "coach-l4", "coach-l5"}


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read CSV with encoding fallback."""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, encoding=encoding, newline="") as f:
                reader = csv.DictReader(f)
                return list(reader)
        except UnicodeDecodeError:
            continue
    print(f"ERROR: Could not decode {path} with any supported encoding")
    sys.exit(1)


def _get(row: dict[str, str], mapping: dict[str, str], field: str) -> str:
    """Get a field from a CSV row using the column mapping. Returns empty string if missing."""
    col = mapping.get(field, "")
    return row.get(col, "").strip() if col else ""


def _parse_date(value: str) -> date | None:
    """Try common date formats."""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_time(value: str) -> time | None:
    """Try common time formats."""
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def _parse_datetime(value: str) -> datetime | None:
    """Try common datetime formats."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=LONDON_TZ)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Members import
# ---------------------------------------------------------------------------


async def import_members(db: AsyncSession, rows: list[dict[str, str]], *, dry_run: bool) -> None:
    """Import member rows into users + org_memberships."""
    # Look up Hackney Tennis org
    result = await db.execute(select(Organisation).where(Organisation.slug == "hackney-tennis"))
    org = result.scalar_one_or_none()
    if not org:
        print("ERROR: Organisation 'hackney-tennis' not found. Run seed first.")
        return

    # Load tier lookup
    result = await db.execute(select(MembershipTier).where(MembershipTier.organisation_id == org.id))
    tiers = {t.slug: t for t in result.scalars().all()}

    # Load existing emails for dedup
    result = await db.execute(select(User.email))
    existing_emails = {email.lower() for email in result.scalars().all()}

    imported = 0
    skipped = 0
    errors: list[str] = []
    now = datetime.now(LONDON_TZ)

    for i, row in enumerate(rows):
        row_num = i + 2  # 1-indexed, +1 for header

        email = _get(row, MEMBER_COLUMNS, "email").lower()
        if not email:
            errors.append(f"Row {row_num}: missing email")
            continue

        if email in existing_emails:
            skipped += 1
            continue

        first_name = _get(row, MEMBER_COLUMNS, "first_name")
        last_name = _get(row, MEMBER_COLUMNS, "last_name")
        if not first_name or not last_name:
            errors.append(f"Row {row_num}: missing name for {email}")
            continue

        # Resolve tier
        tier_raw = _get(row, MEMBER_COLUMNS, "membership_type").lower()
        tier_slug = TIER_MAP.get(tier_raw)
        if not tier_slug or tier_slug not in tiers:
            errors.append(f"Row {row_num}: unknown membership type '{tier_raw}' for {email}")
            continue

        tier = tiers[tier_slug]
        org_role = OrgRole.COACH if tier_slug in COACH_TIER_SLUGS else OrgRole.MEMBER

        # Parse optional fields
        phone = _get(row, MEMBER_COLUMNS, "phone") or None
        dob_str = _get(row, MEMBER_COLUMNS, "date_of_birth")
        dob = _parse_date(dob_str) if dob_str else None
        legacy_id = _get(row, MEMBER_COLUMNS, "member_id") or None
        joined_str = _get(row, MEMBER_COLUMNS, "joined_date")
        joined_at = _parse_datetime(joined_str) if joined_str else None
        expiry_str = _get(row, MEMBER_COLUMNS, "expiry_date")
        expires_at = _parse_datetime(expiry_str) if expiry_str else None

        if dry_run:
            print(f"  [DRY RUN] Would import: {email} ({first_name} {last_name}) as {tier.name} / {org_role.value}")
        else:
            user = User(
                email=email,
                hashed_password=None,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                date_of_birth=dob,
                migrated_from="clubspark",
                migrated_at=now,
                legacy_id=legacy_id,
            )
            db.add(user)
            await db.flush()

            membership = OrgMembership(
                user_id=user.id,
                organisation_id=org.id,
                tier_id=tier.id,
                role=org_role,
                joined_at=joined_at,
                expires_at=expires_at,
            )
            db.add(membership)

        existing_emails.add(email)
        imported += 1

        if (i + 1) % 100 == 0:
            print(f"  Processed {i + 1}/{len(rows)} rows...")

    print(f"\nMembers import {'(DRY RUN) ' if dry_run else ''}complete:")
    print(f"  Imported: {imported}")
    print(f"  Skipped (duplicate email): {skipped}")
    print(f"  Errors: {len(errors)}")
    for err in errors:
        print(f"    {err}")


# ---------------------------------------------------------------------------
# Bookings import
# ---------------------------------------------------------------------------


async def import_bookings(db: AsyncSession, rows: list[dict[str, str]], *, dry_run: bool) -> None:
    """Import booking history rows."""
    # Look up org
    result = await db.execute(select(Organisation).where(Organisation.slug == "hackney-tennis"))
    org = result.scalar_one_or_none()
    if not org:
        print("ERROR: Organisation 'hackney-tennis' not found. Run seed first.")
        return

    # Build user lookup by email
    result = await db.execute(select(User))
    users_by_email: dict[str, User] = {u.email.lower(): u for u in result.scalars().all()}

    # Build user lookup by legacy_id (fallback)
    users_by_legacy: dict[str, User] = {}
    for u in users_by_email.values():
        if u.legacy_id:
            users_by_legacy[u.legacy_id] = u

    # Build resource lookup: (site_name_lower, court_name_lower) -> Resource
    result = await db.execute(
        select(Resource, Site.name.label("site_name")).join(Site).where(Site.organisation_id == org.id)
    )
    resource_lookup: dict[tuple[str, str], Resource] = {}
    for row_result in result.all():
        resource = row_result[0]
        site_name = row_result[1]
        resource_lookup[(site_name.lower(), resource.name.lower())] = resource

    # Build existing booking keys for dedup (resource_id, date, start_time) for confirmed
    result = await db.execute(
        select(Booking.resource_id, Booking.booking_date, Booking.start_time).where(
            Booking.organisation_id == org.id,
            Booking.status == BookingStatus.CONFIRMED,
        )
    )
    existing_bookings: set[tuple[int, date, time]] = set()
    for b in result.all():
        existing_bookings.add((b[0], b[1], b[2]))

    imported = 0
    skipped = 0
    errors: list[str] = []

    for i, row in enumerate(rows):
        row_num = i + 2

        # Resolve user
        email = _get(row, BOOKING_COLUMNS, "email").lower()
        user = users_by_email.get(email)
        if not user:
            booking_id = _get(row, BOOKING_COLUMNS, "booking_id")
            if booking_id:
                user = users_by_legacy.get(booking_id)
        if not user:
            errors.append(f"Row {row_num}: user not found for email '{email}'")
            continue

        # Resolve resource
        venue = _get(row, BOOKING_COLUMNS, "venue").lower()
        court = _get(row, BOOKING_COLUMNS, "court").lower()
        resource = resource_lookup.get((venue, court))
        if not resource:
            errors.append(f"Row {row_num}: court not found: '{venue}' / '{court}'")
            continue

        # Parse date and times
        date_str = _get(row, BOOKING_COLUMNS, "date")
        booking_date = _parse_date(date_str) if date_str else None
        if not booking_date:
            errors.append(f"Row {row_num}: invalid date '{date_str}'")
            continue

        start_str = _get(row, BOOKING_COLUMNS, "start_time")
        start_time = _parse_time(start_str) if start_str else None
        if not start_time:
            errors.append(f"Row {row_num}: invalid start time '{start_str}'")
            continue

        # Calculate end_time and duration
        end_str = _get(row, BOOKING_COLUMNS, "end_time")
        dur_str = _get(row, BOOKING_COLUMNS, "duration_minutes")

        if end_str:
            end_time = _parse_time(end_str)
            if not end_time:
                errors.append(f"Row {row_num}: invalid end time '{end_str}'")
                continue
            start_dt = datetime.combine(booking_date, start_time)
            end_dt = datetime.combine(booking_date, end_time)
            duration_minutes = int((end_dt - start_dt).total_seconds() / 60)
        elif dur_str:
            try:
                duration_minutes = int(dur_str)
            except ValueError:
                errors.append(f"Row {row_num}: invalid duration '{dur_str}'")
                continue
            end_dt = datetime.combine(booking_date, start_time) + timedelta(minutes=duration_minutes)
            end_time = end_dt.time()
        else:
            # Default to 60 minutes
            duration_minutes = 60
            end_dt = datetime.combine(booking_date, start_time) + timedelta(minutes=60)
            end_time = end_dt.time()

        # Status
        status_raw = _get(row, BOOKING_COLUMNS, "status").lower()
        booking_status = STATUS_MAP.get(status_raw, BookingStatus.COMPLETED)

        # Dedup check for confirmed bookings
        if booking_status == BookingStatus.CONFIRMED:
            key = (resource.id, booking_date, start_time)
            if key in existing_bookings:
                skipped += 1
                continue
            existing_bookings.add(key)

        # Amount
        amount_str = _get(row, BOOKING_COLUMNS, "amount_paid")
        amount_pence = 0
        if amount_str:
            with contextlib.suppress(ValueError):
                amount_pence = int(float(amount_str) * 100)

        # Store raw row for audit trail
        extra = dict(row)

        if dry_run:
            print(
                f"  [DRY RUN] Would import: {booking_date} {start_time}-{end_time} "
                f"@ {venue}/{court} for {email} ({booking_status.value})"
            )
        else:
            booking = Booking(
                organisation_id=org.id,
                resource_id=resource.id,
                user_id=user.id,
                booking_date=booking_date,
                start_time=start_time,
                end_time=end_time,
                duration_minutes=duration_minutes,
                status=booking_status,
                source=BookingSource.ADMIN,
                payment_status=PaymentStatus.PAID if amount_pence > 0 else PaymentStatus.NOT_REQUIRED,
                amount_pence=amount_pence,
                extra=extra,
            )
            db.add(booking)

        imported += 1

        if (i + 1) % 100 == 0:
            print(f"  Processed {i + 1}/{len(rows)} rows...")

    print(f"\nBookings import {'(DRY RUN) ' if dry_run else ''}complete:")
    print(f"  Imported: {imported}")
    print(f"  Skipped (duplicate): {skipped}")
    print(f"  Errors: {len(errors)}")
    for err in errors:
        print(f"    {err}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def main(args: argparse.Namespace) -> None:
    path = Path(args.csv_file)
    if not path.exists():
        print(f"ERROR: File not found: {path}")
        sys.exit(1)

    print(f"Reading {path}...")
    rows = _read_csv(path)
    print(f"Found {len(rows)} rows.")

    async with async_session_factory() as db:
        if args.command == "members":
            await import_members(db, rows, dry_run=args.dry_run)
        elif args.command == "bookings":
            await import_bookings(db, rows, dry_run=args.dry_run)

        if not args.dry_run:
            await db.commit()
            print("Committed to database.")
        else:
            await db.rollback()
            print("Dry run — no changes made.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import ClubSpark CSV data into CourtBook")
    sub = parser.add_subparsers(dest="command", required=True)

    members_parser = sub.add_parser("members", help="Import members CSV")
    members_parser.add_argument("csv_file", help="Path to members CSV file")
    members_parser.add_argument("--dry-run", action="store_true", help="Validate without writing to DB")

    bookings_parser = sub.add_parser("bookings", help="Import bookings CSV")
    bookings_parser.add_argument("csv_file", help="Path to bookings CSV file")
    bookings_parser.add_argument("--dry-run", action="store_true", help="Validate without writing to DB")

    parsed = parser.parse_args()
    asyncio.run(main(parsed))
