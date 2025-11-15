export const API_BASE = import.meta.env.VITE_API_BASE || ''
// WS_BASE が未設定でも API_BASE から導出して直結できるようにする
const DERIVED_WS_BASE = API_BASE ? API_BASE.replace(/^http/, 'ws') : ''
export const WS_BASE = import.meta.env.VITE_WS_BASE || DERIVED_WS_BASE

export function api(path: string) {
  if (!API_BASE) return path
  return `${API_BASE}${path}`
}

export function ws(path: string) {
  if (!WS_BASE) return path
  return `${WS_BASE}${path}`
}
