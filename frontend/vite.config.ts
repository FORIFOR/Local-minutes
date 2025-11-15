import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = path.resolve(__dirname, '..')

function hydrateEnvFromRoot() {
  const envPath = path.join(PROJECT_ROOT, '.env')
  if (!fs.existsSync(envPath)) {
    return
  }
  const lines = fs.readFileSync(envPath, 'utf8').split(/\r?\n/)
  for (const rawLine of lines) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const eq = line.indexOf('=')
    if (eq <= 0) continue
    const key = line.slice(0, eq).trim()
    if (!/^VITE_/i.test(key) && key !== 'BACKEND_PROXY_TARGET' && key !== 'PORT_BACKEND') {
      continue
    }
    if (process.env[key] !== undefined) {
      continue
    }
    let value = line.slice(eq + 1)
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1)
    }
    process.env[key] = value
  }
}

hydrateEnvFromRoot()

function resolveProxyTarget(env: Record<string, string>) {
  const direct =
    process.env.BACKEND_PROXY_TARGET ||
    env.BACKEND_PROXY_TARGET
  if (direct && direct.trim()) {
    return direct.trim()
  }
  const candidates = [
    path.join(process.cwd(), '.backend_port'),
    path.join(path.resolve(process.cwd(), '..'), '.backend_port'),
    path.join(PROJECT_ROOT, '.backend_port'),
  ]
  for (const portFile of candidates) {
    if (fs.existsSync(portFile)) {
      try {
        const raw = fs.readFileSync(portFile, 'utf8').trim()
        const port = Number(raw)
        if (Number.isInteger(port) && port > 0) {
          return `http://127.0.0.1:${port}`
        }
      } catch {
        // ignore and try next candidate
      }
    }
  }
  const fallbackPort = process.env.PORT_BACKEND || env.PORT_BACKEND || '8000'
  return `http://127.0.0.1:${fallbackPort}`
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = resolveProxyTarget(env)
  const wsTarget = proxyTarget.replace(/^http/, 'ws')
  const extraAllowed = (process.env.VITE_ALLOWED_HOSTS || env.VITE_ALLOWED_HOSTS || '')
    .split(',')
    .map((h) => h.trim())
    .filter(Boolean)
  const allowedHosts = Array.from(
    new Set([
      'responding-arlington-detection-vice.trycloudflare.com',
      'sullivan-ronald-functions-gif.trycloudflare.com',
      'calm-sie-homeland-extending.trycloudflare.com',
      'custody-update-roof-determine.trycloudflare.com',
      ...extraAllowed,
    ])
  )

  return {
    plugins: [react()],
    server: {
      port: Number(process.env.DEV_FRONTEND_PORT || env.DEV_FRONTEND_PORT || 5173),
      host: process.env.DEV_FRONTEND_HOST || env.DEV_FRONTEND_HOST || '0.0.0.0',
      allowedHosts,
      headers: {
        'Cross-Origin-Opener-Policy': 'same-origin',
        'Cross-Origin-Embedder-Policy': 'require-corp',
      },
      proxy: {
        '/api': proxyTarget,
        '/healthz': proxyTarget,
        '/ws': { target: wsTarget, ws: true },
        '/download.srt': proxyTarget,
        '/download.vtt': proxyTarget,
        '/download.rttm': proxyTarget,
        '/download.ics': proxyTarget,
      },
    },
  }
})
