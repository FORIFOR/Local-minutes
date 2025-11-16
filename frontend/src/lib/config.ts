const CLOUD_API = import.meta.env.VITE_API_BASE || ''
const LOCAL_API = import.meta.env.VITE_LOCAL_API_BASE || ''

export const API_BASE = CLOUD_API
const DERIVED_WS_BASE = API_BASE ? API_BASE.replace(/^http/, 'ws') : ''
export const WS_BASE = import.meta.env.VITE_WS_BASE || DERIVED_WS_BASE

const LOCAL_PREFIXES = [
  "/api/events",
  "/api/cloud",
  "/api/ws",
  "/api/recorder",
  "/api/auth/google",
  "/api/auth/login",
  "/api/auth/register",
  "/api/auth/me",
]

function shouldUseLocal(path: string): boolean {
  return LOCAL_PREFIXES.some((prefix) => path.startsWith(prefix))
}

export function api(path: string) {
  if (shouldUseLocal(path) && LOCAL_API) {
    return `${LOCAL_API}${path}`
  }
  if (!API_BASE) return path
  return `${API_BASE}${path}`
}

/**
 * credentials=include 付きで JSON を取得するヘルパー
 */
export async function apiFetch(path: string, init: RequestInit = {}) {
  const res = await fetch(api(path), {
    ...init,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  })
  if (!res.ok) {
    throw Object.assign(new Error(`API ${res.status}`), { status: res.status })
  }
  try {
    return await res.json()
  } catch {
    return null
  }
}

export function ws(path: string) {
  if (!WS_BASE) return path
  return `${WS_BASE}${path}`
}
