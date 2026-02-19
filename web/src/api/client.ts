/**
 * Fetch wrapper with JWT interceptor and auto-refresh.
 *
 * Access token is held in module-level memory (never localStorage).
 * Refresh token is in localStorage for session persistence.
 */

import { API_PREFIX } from '../lib/constants'
import { clearRefreshToken, getRefreshToken, setRefreshToken } from '../lib/storage'

let accessToken: string | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export function getAccessToken(): string | null {
  return accessToken
}

interface ApiError {
  detail: string | Array<{ rule?: string; message?: string; msg?: string }>
}

export class ApiRequestError extends Error {
  status: number
  detail: ApiError['detail']

  constructor(status: number, detail: ApiError['detail']) {
    const msg = typeof detail === 'string' ? detail : JSON.stringify(detail)
    super(msg)
    this.status = status
    this.detail = detail
  }
}

async function refreshAccessToken(): Promise<boolean> {
  const rt = getRefreshToken()
  if (!rt) return false

  try {
    const res = await fetch(`${API_PREFIX}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    })
    if (!res.ok) {
      clearRefreshToken()
      accessToken = null
      return false
    }
    const data = await res.json()
    accessToken = data.access_token
    setRefreshToken(data.refresh_token)
    return true
  } catch {
    return false
  }
}

/**
 * Typed fetch wrapper. Automatically attaches JWT and retries on 401.
 */
export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${API_PREFIX}${path}`

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  }
  if (accessToken) {
    headers['Authorization'] = `Bearer ${accessToken}`
  }

  let res = await fetch(url, { ...options, headers })

  // Auto-refresh on 401
  if (res.status === 401 && accessToken) {
    const refreshed = await refreshAccessToken()
    if (refreshed) {
      headers['Authorization'] = `Bearer ${accessToken}`
      res = await fetch(url, { ...options, headers })
    }
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiRequestError(res.status, body.detail ?? res.statusText)
  }

  // 204 No Content
  if (res.status === 204) {
    return undefined as T
  }

  return res.json()
}
