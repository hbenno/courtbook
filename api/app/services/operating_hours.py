"""Operating hours and slot generation for court availability.

Pure calculation module — no database, no async, no FastAPI dependencies.
Uses the astral library to compute sunset times for non-floodlit courts.
"""

from datetime import date, datetime, time, timedelta

from astral import LocationInfo
from astral.sun import sunset

from app.services.booking_rules import LONDON_TZ

OPEN_TIME = time(7, 0)  # 07:00 daily open
MAX_CLOSE = time(21, 0)  # 21:00 hard cap (floodlit close, and non-floodlit cap)
SLOT_MINUTES = 60

# Centroid of Hackney — good enough for sunset across all 7 parks.
# The difference in sunset across a ~4 km borough is <20 seconds.
_HACKNEY = LocationInfo("Hackney", "England", "Europe/London", latitude=51.545, longitude=-0.056)


def closing_time(has_floodlights: bool, is_indoor: bool, query_date: date) -> time:
    """Return the wall-clock closing time (London) for a court on query_date.

    Floodlit or indoor courts: always 21:00.
    Non-floodlit outdoor courts: sunset on the Monday of the same ISO week,
    floored to the hour, capped at 21:00.
    """
    if has_floodlights or is_indoor:
        return MAX_CLOSE

    # Monday of the same ISO week (weekday() is 0=Mon)
    monday = query_date - timedelta(days=query_date.weekday())

    sun_set = sunset(_HACKNEY.observer, date=monday, tzinfo=LONDON_TZ)

    # Floor to the hour (e.g. 16:47 → 16:00)
    floored = sun_set.replace(minute=0, second=0, microsecond=0).time()

    if floored > MAX_CLOSE:
        return MAX_CLOSE
    if floored < OPEN_TIME:
        return OPEN_TIME
    return floored


def generate_slots(
    has_floodlights: bool,
    is_indoor: bool,
    query_date: date,
    booked_intervals: list[tuple[time, time]],
) -> list[dict]:
    """Generate all 60-minute slots for a court on a given date.

    Returns a list of dicts with keys: start_time, end_time, is_available.
    Past slots and slots overlapping confirmed bookings are marked unavailable.
    Uses half-open interval overlap (same logic as booking_rules.check_court_conflict).
    """
    close = closing_time(has_floodlights, is_indoor, query_date)
    now = datetime.now(LONDON_TZ)

    slots: list[dict] = []
    current = datetime.combine(query_date, OPEN_TIME, tzinfo=LONDON_TZ)
    end_of_play = datetime.combine(query_date, close, tzinfo=LONDON_TZ)

    while current + timedelta(minutes=SLOT_MINUTES) <= end_of_play:
        slot_start = current.time()
        slot_end = (current + timedelta(minutes=SLOT_MINUTES)).time()

        is_past = current <= now
        has_conflict = any(b_start < slot_end and b_end > slot_start for b_start, b_end in booked_intervals)

        slots.append(
            {
                "start_time": slot_start.strftime("%H:%M"),
                "end_time": slot_end.strftime("%H:%M"),
                "is_available": not is_past and not has_conflict,
            }
        )
        current += timedelta(minutes=SLOT_MINUTES)

    return slots
