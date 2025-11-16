const CLOUD_API = (import.meta.env.VITE_API_BASE || '').trim()
const LOCAL_API = (import.meta.env.VITE_LOCAL_API_BASE || '').trim()
const isDev = import.meta.env.DEV

export const API_BASE = CLOUD_API
const DERIVED_WS_BASE = API_BASE ? API_BASE.replace(/^http/, 'ws') : ''
export const WS_BASE = (import.meta.env.VITE_WS_BASE || DERIVED_WS_BASE).trim()
const LOCAL_WS_BASE = LOCAL_API ? LOCAL_API.replace(/^http/, 'ws') : ''

export const hasLocalBackend = Boolean(LOCAL_API) || isDev

type ApiTarget = 'cloud' | 'local'

function buildUrl(base: string, path: string) {
  if (!path.startsWith('/')) {
    return path
  }
  if (!base) {
    return path
  }
  return `${base}${path}`
}

function ensureLocalPath(path: string) {
  if (LOCAL_API) {
    return `${LOCAL_API}${path}`
  }
  if (isDev) {
    return path
  }
  throw new Error('LOCAL_BACKEND_UNAVAILABLE')
}

export function api(path: string, target: ApiTarget = 'cloud') {
  if (target === 'local') {
    return ensureLocalPath(path)
  }
  return buildUrl(API_BASE, path)
}

export function localApi(path: string) {
  return api(path, 'local')
}

/**
 * credentials=include 付きで JSON を取得するヘルパー
 */
export async function apiFetch(path: string, init: RequestInit = {}, target: ApiTarget = 'cloud') {
  const url = target === 'local' ? ensureLocalPath(path) : buildUrl(API_BASE, path)
  const res = await fetch(url, {
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

export function localWs(path: string) {
  if (LOCAL_WS_BASE) {
    return `${LOCAL_WS_BASE}${path}`
  }
  if (isDev) {
    return path
  }
  throw new Error('LOCAL_BACKEND_UNAVAILABLE')
}
