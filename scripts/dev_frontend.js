// scripts/dev_frontend.js
import getPort from 'get-port'
import { execa } from 'execa'
import open from 'open'
import waitOn from 'wait-on'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import fs from 'node:fs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(__dirname, '..')
const frontendDir = path.resolve(root, 'frontend')

// .env 読み込み（任意）
const envPath = path.join(root, '.env')
if (fs.existsSync(envPath)) {
  const lines = fs
    .readFileSync(envPath, 'utf8')
    .split('\n')
    .filter((l) => l && !l.startsWith('#'))
  for (const line of lines) {
    const [k, ...rest] = line.split('=')
    process.env[k] = rest.join('=')
  }
}

function readBackendPortSync() {
  const portFile = path.join(root, '.backend_port')
  if (fs.existsSync(portFile)) {
    const s = fs.readFileSync(portFile, 'utf8').trim()
    const n = Number(s)
    if (Number.isInteger(n) && n > 0) return n
  }
  return null
}

async function main() {
  // 5173〜5180 の範囲で空きを検索（get-port v7はmakeRange無しのため配列で指定）
  const candidates = Array.from({ length: 8 }, (_, i) => 5173 + i)
  const port = await getPort({ port: candidates })
  const host = 'localhost'
  const url = `http://${host}:${port}/`

  // Backend の実ポート（.backend_port に書かれていればそれを使用）
  // 最大5秒ほど待機して、ファイル生成を待つ
  let backendPort = readBackendPortSync()
  const deadline = Date.now() + 5000
  while (!backendPort && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 200))
    backendPort = readBackendPortSync()
  }
  const apiBase = `http://localhost:${backendPort || process.env.PORT_BACKEND || 8000}`

  // Vite を子プロセスで起動（--host/--port を渡す）
  const vite = execa(
    process.platform === 'win32' ? 'npm.cmd' : 'npm',
    ['run', 'dev', '--', '--host', host, '--port', String(port)],
    { cwd: frontendDir, stdio: 'inherit', env: { ...process.env, VITE_API_BASE: apiBase } }
  )

  // 起動を待ってからブラウザを開く
  await waitOn({ resources: [url], timeout: 60000 })
  // UI 表示は "UI: localhost:3001" の形式
  console.log(`UI: localhost:${port}`)
  await open(url)

  // Vite が落ちるまで待機（Ctrl+C で全体停止）
  await vite
}

main().catch((err) => {
  console.error('dev_frontend failed:', err)
  process.exit(1)
})
