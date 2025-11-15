import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/config'
import { navigateApp } from '../lib/navigation'

type EventRow = {
  id: string
  title: string
  start_ts: number
  end_ts?: number
  lang?: string
}

type Status = '予定' | '録音中' | '処理中' | '完了' | '要確認'

function formatDate(ts: number) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
}

function durationStr(start?: number, end?: number) {
  if (!start || !end || end <= start) return '-'
  const m = Math.round((end - start) / 60)
  if (m < 60) return `${m}分`
  const h = Math.floor(m / 60)
  const mm = m % 60
  return `${h}時間${mm ? mm + '分' : ''}`
}

export default function DbTable() {
  const [rows, setRows] = useState<EventRow[]>([])
  const [meta, setMeta] = useState<Record<string, { status: Status; summaryLine?: string }>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const r = await fetch(api('/api/events?limit=200'), { cache: 'no-store' as any })
      const j = await r.json()
      const items: EventRow[] = j.items || []
      setRows(items)
      // 行ごとに軽量メタを非同期取得（要約/レコーディング有無）
      // 最小実装: 要約があれば完了、record.wavがあれば録音済、それ以外は予定
      items.slice(0, 50).forEach(async (ev) => {
        try {
          const [evRes, artRes] = await Promise.all([
            fetch(api(`/api/events/${ev.id}`), { cache: 'no-store' as any }),
            fetch(api(`/api/events/${ev.id}/artifacts`), { cache: 'no-store' as any }),
          ])
          const evJ = await evRes.json()
          const artJ = await artRes.json()
          const hasSummary = !!evJ?.summary?.text_md
          const hasRecord = (artJ?.items || []).some((x: any) => x.name === 'record.wav' && x.size > 0)
          const status: Status = hasSummary ? '完了' : hasRecord ? '処理中' : '予定'
          const summaryLine = hasSummary ? String(evJ.summary.text_md || '').split(/\n|。/)[0]?.slice(0, 80) : undefined
          setMeta((m) => ({ ...m, [ev.id]: { status, summaryLine } }))
        } catch (e) {
          setMeta((m) => ({ ...m, [ev.id]: { status: '要確認' } }))
        }
      })
    } catch (e) {
      setError('一覧の取得に失敗しました')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-sm text-[--muted]">最新{rows.length}件</div>
        <button className="btn btn-ghost" onClick={load}>再読み込み</button>
      </div>
      <div className="overflow-auto rounded-xl border border-black/10 dark:border-white/10">
        <table className="min-w-full text-sm">
          <thead className="bg-black/5 dark:bg-white/5">
            <tr>
              <th className="px-3 py-2 text-left w-[84px]">状態</th>
              <th className="px-3 py-2 text-left">タイトル</th>
              <th className="px-3 py-2 text-left w-[160px]">日時</th>
              <th className="px-3 py-2 text-left w-[88px]">所要</th>
              <th className="px-3 py-2 text-left">要約抜粋</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((ev) => {
              const m = meta[ev.id]
              const st = m?.status || '予定'
              const stCls =
                st === '完了' ? 'bg-green-500/20 text-green-700 dark:text-green-200' :
                st === '処理中' ? 'bg-yellow-500/20 text-yellow-800 dark:text-yellow-200' :
                st === '録音中' ? 'bg-blue-500/20 text-blue-800 dark:text-blue-200' :
                st === '要確認' ? 'bg-red-500/20 text-red-800 dark:text-red-200' : 'bg-gray-500/20 text-gray-700 dark:text-gray-300'
              return (
                <tr
                  key={ev.id}
                  className="border-t border-black/5 dark:border-white/5 hover:bg-black/5 dark:hover:bg-white/5 cursor-pointer"
                  onClick={()=> navigateApp(`/meetings/${ev.id}`)}
                >
                  <td className="px-3 py-2"><span className={`px-2 py-0.5 rounded ${stCls}`}>{st}</span></td>
                  <td className="px-3 py-2"><Link to={`/meetings/${ev.id}`} className="underline hover:no-underline">{ev.title || ev.id}</Link></td>
                  <td className="px-3 py-2 whitespace-nowrap">{formatDate(ev.start_ts)}</td>
                  <td className="px-3 py-2">{durationStr(ev.start_ts, ev.end_ts)}</td>
                  <td className="px-3 py-2 text-[color:var(--muted)] truncate max-w-[240px]">{m?.summaryLine || '-'}</td>
                </tr>
              )
            })}
            {rows.length === 0 && !loading && (
              <tr><td colSpan={5} className="px-3 py-8 text-center text-[--muted]">データがありません。右上から新規作成してください。</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {error && <div className="text-red-600 text-sm">{error}</div>}
    </div>
  )
}
