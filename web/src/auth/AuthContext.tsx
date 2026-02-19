import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'
import { setAccessToken } from '../api/client'
import * as api from '../api/endpoints'
import { clearRefreshToken, getRefreshToken, setRefreshToken } from '../lib/storage'
import type { LoginRequest, RegisterRequest, User } from '../types/api'

interface AuthState {
  user: User | null
  loading: boolean
  login: (body: LoginRequest) => Promise<void>
  register: (body: RegisterRequest) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  // Restore session from refresh token on mount
  useEffect(() => {
    const rt = getRefreshToken()
    if (!rt) {
      setLoading(false)
      return
    }
    api
      .getMe()
      .then(setUser)
      .catch(() => {
        clearRefreshToken()
        setAccessToken(null)
      })
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (body: LoginRequest) => {
    const tokens = await api.login(body)
    setAccessToken(tokens.access_token)
    setRefreshToken(tokens.refresh_token)
    const me = await api.getMe()
    setUser(me)
  }, [])

  const register = useCallback(async (body: RegisterRequest) => {
    const tokens = await api.register(body)
    setAccessToken(tokens.access_token)
    setRefreshToken(tokens.refresh_token)
    const me = await api.getMe()
    setUser(me)
  }, [])

  const logout = useCallback(() => {
    setAccessToken(null)
    clearRefreshToken()
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
