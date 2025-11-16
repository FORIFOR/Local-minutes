import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../lib/config'

type User = {
  id: number
  email: string
  name: string
}

type AuthContextValue = {
  user: User | null
  loading: boolean
  authError: string | null
  login: (email: string, password: string) => Promise<void>
  register: (name: string, email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
  clearError: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)
const TOKEN_KEY = 'accessToken'

const getStoredToken = () => localStorage.getItem(TOKEN_KEY)
const storeToken = (token?: string | null) => {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_KEY)
  }
}

async function jsonRequest(path: string, init: RequestInit = {}) {
  const res = await fetch(api(path), {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
    credentials: 'include',
  })
  let body: any = null
  try {
    body = await res.json()
  } catch {
    body = null
  }
  if (!res.ok) {
    const detail = body?.detail || body?.message || 'エラーが発生しました'
    throw new Error(detail)
  }
  return body
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [authError, setAuthError] = useState<string | null>(null)

  const fetchMe = useCallback(async () => {
    setLoading(true)
    try {
      const headers: HeadersInit = {}
      const token = getStoredToken()
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(api('/api/auth/me'), { credentials: 'include', headers })
      if (!res.ok) {
        storeToken(null)
        setUser(null)
        return
      }
      const data = await res.json()
      setUser(data)
    } catch {
      storeToken(null)
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetchMe()
  }, [fetchMe])

  const applyPayload = useCallback((payload: any) => {
    if (!payload) return
    if (payload.token) {
      storeToken(payload.token)
    }
    const { token, ...rest } = payload
    setUser(rest)
  }, [])

  const loginRequest = useCallback(
    async (email: string, password: string) => {
      setAuthError(null)
      const body = await jsonRequest('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      })
      applyPayload(body)
    },
    [applyPayload]
  )

  const registerRequest = useCallback(
    async (name: string, email: string, password: string) => {
      setAuthError(null)
      const body = await jsonRequest('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify({ name, email, password }),
      })
      applyPayload(body)
    },
    [applyPayload]
  )

  const logout = useCallback(async () => {
    setAuthError(null)
    try {
      await jsonRequest('/api/auth/logout', { method: 'POST' })
    } catch {
      /* ignore logout errors */
    } finally {
      storeToken(null)
      setUser(null)
    }
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      authError,
      login: async (email, password) => {
        try {
          await loginRequest(email, password)
        } catch (err) {
          setAuthError(err instanceof Error ? err.message : 'ログインに失敗しました')
          throw err
        }
      },
      register: async (name, email, password) => {
        try {
          await registerRequest(name, email, password)
        } catch (err) {
          setAuthError(err instanceof Error ? err.message : '登録に失敗しました')
          throw err
        }
      },
      logout,
      refresh: fetchMe,
      clearError: () => setAuthError(null),
    }),
    [user, loading, authError, loginRequest, registerRequest, logout, fetchMe]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return ctx
}
