"""Pricing service for booking fee calculation.

Determines the price band (early/offpeak/peak/floodlight) and calculates
the fee from the member's tier. Time band boundaries are configurable per
organisation via the org.config JSONB field.
"""

from datetime import date, datetime, time, timedelta

from app.models.member import MembershipTier
from app.models.organisation import Resource
from app.services.operating_hours import closing_time

# Price band constants
BAND_EARLY = "early"
BAND_OFFPEAK = "offpeak"
BAND_PEAK = "peak"
BAND_FLOODLIGHT = "floodlight"

# Default time band boundaries — overridable per org via org.config
DEFAULTS = {
    "weekday_early_end": "10:00",
    "weekday_peak_start": "18:00",
    "weekend_early_end": "09:00",
}


def _parse_time(s: str) -> time:
    h, m = map(int, s.split(":"))
    return time(h, m)


def _dusk_time(query_date: date) -> time:
    """When floodlights would be needed — reuses the non-floodlit court closing time."""
    return closing_time(has_floodlights=False, is_indoor=False, query_date=query_date)


def _calc_end_time(start_time: time, duration_minutes: int) -> time:
    start_dt = _combine(start_time)
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    return end_dt.time()


def _combine(t: time) -> datetime:
    """Combine a time with an arbitrary date for arithmetic."""
    return datetime.combine(date.today(), t)


def determine_price_band(
    resource: Resource,
    booking_date: date,
    start_time: time,
    end_time: time,
    org_config: dict | None = None,
) -> str:
    """Determine the pricing band for a booking.

    Floodlight: floodlit court AND any part of booking after dusk (overrides other bands).
    Otherwise: early/offpeak/peak based on time of day and day of week.
    """
    config = org_config or {}

    # Floodlight check: court has lights AND booking extends past dusk
    if resource.has_floodlights:
        dusk = _dusk_time(booking_date)
        if end_time > dusk:
            return BAND_FLOODLIGHT

    is_weekend = booking_date.weekday() >= 5

    if is_weekend:
        early_end = _parse_time(config.get("weekend_early_end", DEFAULTS["weekend_early_end"]))
        if start_time < early_end:
            return BAND_EARLY
        return BAND_PEAK
    else:
        early_end = _parse_time(config.get("weekday_early_end", DEFAULTS["weekday_early_end"]))
        peak_start = _parse_time(config.get("weekday_peak_start", DEFAULTS["weekday_peak_start"]))
        if start_time < early_end:
            return BAND_EARLY
        if start_time >= peak_start:
            return BAND_PEAK
        return BAND_OFFPEAK


def calculate_booking_fee(
    tier: MembershipTier,
    resource: Resource,
    booking_date: date,
    start_time: time,
    duration_minutes: int,
    org_config: dict | None = None,
) -> tuple[int, str]:
    """Calculate the booking fee in pence.

    Returns (fee_pence, band). Fee scales linearly with duration
    (fees stored per hour on the tier).
    """
    end_time = _calc_end_time(start_time, duration_minutes)
    band = determine_price_band(resource, booking_date, start_time, end_time, org_config)

    fee_per_hour = {
        BAND_EARLY: tier.early_booking_fee_pence,
        BAND_OFFPEAK: tier.offpeak_booking_fee_pence,
        BAND_PEAK: tier.peak_booking_fee_pence,
        BAND_FLOODLIGHT: tier.floodlight_booking_fee_pence,
    }[band]

    fee_pence = fee_per_hour * duration_minutes // 60
    return fee_pence, band
