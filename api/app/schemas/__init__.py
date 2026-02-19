"""Pydantic schemas for API serialisation."""

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, EmailStr

# --- Auth ---


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str
    phone: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


# --- Organisation ---


class OrganisationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    is_active: bool
    email: str | None
    website: str | None


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    is_active: bool
    address: str | None
    postcode: str | None


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    resource_type: str
    is_active: bool
    surface: str | None
    is_indoor: bool
    has_floodlights: bool


# --- Booking ---


class BookingCreate(BaseModel):
    resource_id: int
    booking_date: date
    start_time: time
    duration_minutes: int = 60


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resource_id: int
    user_id: int
    booking_date: date
    start_time: time
    end_time: time
    duration_minutes: int
    status: str
    source: str
    payment_status: str
    amount_pence: int
    created_at: datetime


# --- User ---


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    first_name: str
    last_name: str
    phone: str | None
    role: str


class MembershipTierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    advance_booking_days: int
    max_concurrent_bookings: int
    max_daily_minutes: int
    cancellation_deadline_hours: int
    peak_booking_fee_pence: int
    offpeak_booking_fee_pence: int


# --- Org Membership (admin views) ---


class OrgMembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    role: str
    is_active: bool
    joined_at: datetime | None
    tier: MembershipTierOut
    user: UserOut


# --- Availability ---


class SlotOut(BaseModel):
    start_time: str  # "HH:MM"
    end_time: str  # "HH:MM"
    is_available: bool


class AvailabilityOut(BaseModel):
    court_id: int
    court_name: str
    date: date
    slots: list[SlotOut]


# --- Preferences ---


class PreferenceIn(BaseModel):
    site_id: int | None = None
    resource_id: int | None = None
    day_of_week: int | None = None
    preferred_start_time: time | None = None
    duration_minutes: int = 60


class PreferenceOut(BaseModel):
    id: int
    priority: int
    site_id: int | None
    site_name: str | None
    resource_id: int | None
    resource_name: str | None
    day_of_week: int | None
    preferred_start_time: time | None
    duration_minutes: int


class PreferencesReplace(BaseModel):
    preferences: list[PreferenceIn]
