import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/config'

export type ActionItem = {
  id: number
  side: 'client' | 'self'
  assignee: string
  due_ts: number
  content: string
  done: number
}

export default function ActionList({ eventId }: { eventId: string }) {
  const [items, setItems] = useState<ActionItem[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const load = async () => {
    setLoading(true)
    setErr('')
    try {
      const r = await fetch(api(`/api/events/${eventId}/actions`), { cache: 'no-store' as any })
      const j = await r.json()
      setItems(j.items || [])
    } catch (e) {
      setErr('アクションの取得に失敗しました')
    } finally { setLoading(false) }
  }

  useEffect(() => { if (eventId) load() }, [eventId])

  const add = async () => {
    const content = prompt('アクションの内容')
    if (!content) return
    const assignee = prompt('担当者（例: 田中）') || ''
    const side = (prompt('担当区分（client/self）', 'self') || 'self') as any
    const due = prompt('期限（YYYY-MM-DD）')
    const due_ts = due ? Math.floor(new Date(due).getTime()/1000) : 0
    const r = await fetch(api(`/api/events/${eventId}/actions`), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content, assignee, side, due_ts }) })
    const j = await r.json()
    setItems(prev => [...prev, { id: j.id, content, assignee, side, due_ts, done: 0 } as any])
  }

  const toggle = async (it: ActionItem) => {
    const done = it.done ? 0 : 1
    await fetch(api(`/api/events/${eventId}/actions/${it.id}`), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ done }) })
    setItems(prev => prev.map(x => x.id === it.id ? { ...x, done } : x))
  }

  const del = async (it: ActionItem) => {
    if (!confirm('このアクションを削除しますか？')) return
    await fetch(api(`/api/events/${eventId}/actions/${it.id}`), { method: 'DELETE' })
    setItems(prev => prev.filter(x => x.id !== it.id))
  }

  const fmtDate = (ts: number) => ts ? new Date(ts*1000).toLocaleDateString() : '-'

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="font-semibold">アクション</div>
        <button className="btn btn-ghost" onClick={add}>+ 追加</button>
      </div>
      <div className="overflow-auto rounded-xl border border-black/10 dark:border-white/10">
        <table className="min-w-full text-sm">
          <thead className="bg-black/5 dark:bg-white/5">
            <tr>
              <th className="px-3 py-2 text-left w-[40px]">完了</th>
              <th className="px-3 py-2 text-left w-[80px]">区分</th>
              <th className="px-3 py-2 text-left w-[120px]">担当</th>
              <th className="px-3 py-2 text-left w-[120px]">期限</th>
              <th className="px-3 py-2 text-left">内容</th>
              <th className="px-3 py-2 text-left w-[60px]"></th>
            </tr>
          </thead>
          <tbody>
            {items.map(it => (
              <tr key={it.id} className="border-t border-black/5 dark:border-white/5 hover:bg-black/5 dark:hover:bg-white/5">
                <td className="px-3 py-2"><input type="checkbox" checked={!!it.done} onChange={()=>toggle(it)} /></td>
                <td className="px-3 py-2">{it.side}</td>
                <td className="px-3 py-2">{it.assignee || '-'}</td>
                <td className="px-3 py-2 whitespace-nowrap">{fmtDate(it.due_ts)}</td>
                <td className="px-3 py-2">{it.content}</td>
                <td className="px-3 py-2"><button className="btn btn-ghost" onClick={()=>del(it)}>削除</button></td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-[--muted]">まだアクションはありません</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {err && <div className="text-red-600 text-sm">{err}</div>}
    </div>
  )
}

