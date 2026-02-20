/**
 * Typed API call functions — one per backend endpoint.
 */

import { apiFetch } from './client'
import { ORG_SLUG } from '../lib/constants'
import type {
  Availability,
  Booking,
  BookingCreate,
  LoginRequest,
  Preference,
  PreferenceIn,
  RegisterRequest,
  Resource,
  Site,
  SiteAvailability,
  TokenResponse,
  User,
} from '../types/api'

// --- Auth ---

export function login(body: LoginRequest) {
  return apiFetch<TokenResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function register(body: RegisterRequest) {
  return apiFetch<TokenResponse>('/auth/register', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getMe() {
  return apiFetch<User>('/auth/me')
}

export function forgotPassword(email: string) {
  return apiFetch<{ message: string }>('/auth/forgot-password', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

export function resetPassword(token: string, new_password: string) {
  return apiFetch<{ message: string }>('/auth/reset-password', {
    method: 'POST',
    body: JSON.stringify({ token, new_password }),
  })
}

// --- Organisation / Sites / Courts ---

export function getSites() {
  return apiFetch<Site[]>(`/orgs/${ORG_SLUG}/sites`)
}

export function getCourts(siteSlug: string) {
  return apiFetch<Resource[]>(`/orgs/${ORG_SLUG}/sites/${siteSlug}/courts`)
}

// --- Availability ---

export function getAvailability(siteSlug: string, courtId: number, date: string) {
  return apiFetch<Availability>(
    `/orgs/${ORG_SLUG}/sites/${siteSlug}/courts/${courtId}/availability?date=${date}`,
  )
}

export function getSiteAvailability(siteSlug: string, date: string) {
  return apiFetch<SiteAvailability>(
    `/orgs/${ORG_SLUG}/sites/${siteSlug}/availability?date=${date}`,
  )
}

// --- Bookings ---

export function createBooking(body: BookingCreate) {
  return apiFetch<Booking>('/bookings', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getMyBookings() {
  return apiFetch<Booking[]>('/bookings')
}

export function cancelBooking(bookingId: number) {
  return apiFetch<void>(`/bookings/${bookingId}`, { method: 'DELETE' })
}

// --- Preferences ---

export function getPreferences() {
  return apiFetch<Preference[]>(`/orgs/${ORG_SLUG}/preferences`)
}

export function replacePreferences(preferences: PreferenceIn[]) {
  return apiFetch<Preference[]>(`/orgs/${ORG_SLUG}/preferences`, {
    method: 'PUT',
    body: JSON.stringify({ preferences }),
  })
}
