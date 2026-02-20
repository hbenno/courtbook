/** TypeScript interfaces mirroring the backend Pydantic schemas. */

// --- Auth ---

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  password: string
  first_name: string
  last_name: string
  phone?: string
}

// --- User ---

export interface User {
  id: number
  email: string
  first_name: string
  last_name: string
  phone: string | null
  role: string
}

// --- Organisation ---

export interface Organisation {
  id: number
  name: string
  slug: string
  is_active: boolean
  email: string | null
  website: string | null
}

export interface Site {
  id: number
  name: string
  slug: string
  is_active: boolean
  address: string | null
  postcode: string | null
}

export interface Resource {
  id: number
  name: string
  slug: string
  resource_type: string
  is_active: boolean
  surface: string | null
  is_indoor: boolean
  has_floodlights: boolean
}

// --- Availability ---

export interface Slot {
  start_time: string // "HH:MM"
  end_time: string   // "HH:MM"
  is_available: boolean
}

export interface Availability {
  court_id: number
  court_name: string
  date: string // "YYYY-MM-DD"
  slots: Slot[]
}

export interface CourtAvailability {
  court_id: number
  court_name: string
  has_floodlights: boolean
  surface: string | null
  slots: Slot[]
}

export interface SiteAvailability {
  site_id: number
  site_name: string
  date: string // "YYYY-MM-DD"
  courts: CourtAvailability[]
}

// --- Booking ---

export interface BookingCreate {
  resource_id: number
  booking_date: string // "YYYY-MM-DD"
  start_time: string   // "HH:MM:SS"
  duration_minutes: number
}

export interface Booking {
  id: number
  resource_id: number
  user_id: number
  booking_date: string // "YYYY-MM-DD"
  start_time: string   // "HH:MM:SS"
  end_time: string     // "HH:MM:SS"
  duration_minutes: number
  status: string
  source: string
  payment_status: string
  amount_pence: number
  created_at: string
  client_secret: string | null
}

// --- Preferences ---

export interface PreferenceIn {
  site_id?: number | null
  resource_id?: number | null
  day_of_week?: number | null
  preferred_start_time?: string | null // "HH:MM:SS"
  duration_minutes: number
}

export interface Preference {
  id: number
  priority: number
  site_id: number | null
  site_name: string | null
  resource_id: number | null
  resource_name: string | null
  day_of_week: number | null
  preferred_start_time: string | null
  duration_minutes: number
}
