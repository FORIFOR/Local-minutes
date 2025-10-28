import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: (() => {
      // 環境変数から API ベースURL を取得（未指定は 127.0.0.1:8000）
      const env = loadEnv(process.env.NODE_ENV || 'development', process.cwd(), '')
      const apiBase = env.VITE_API_BASE || 'http://127.0.0.1:8002'
      const wsBase = apiBase.replace(/^http/, 'ws')
      return {
        '/api': apiBase,
        '/healthz': apiBase,
        '/ws': { target: wsBase, ws: true },
        '/download.srt': apiBase,
        '/download.vtt': apiBase,
        '/download.rttm': apiBase,
        '/download.ics': apiBase,
      }
    })()
  }
})
