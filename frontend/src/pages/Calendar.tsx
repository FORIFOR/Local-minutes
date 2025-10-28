import { useEffect, useMemo, useState } from 'react'
import CalendarMonth from '../components/CalendarMonth'
import DbTable from '../components/DbTable'
import { api } from '../lib/config'
import * as Dialog from '@radix-ui/react-dialog'

type Ev = { id: string; title: string; start_ts: number; end_ts?: number }

export default function Calendar() {
  const today = new Date()
  const [year, setYear] = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth()) // 0-based
  const [events, setEvents] = useState<Ev[]>([])
  const [open, setOpen] = useState(false)
  const [draftDate, setDraftDate] = useState<Date | null>(null)
  const [title, setTitle] = useState('')

  const range = useMemo(() => {
    const from = new Date(year, month, 1)
    const to = new Date(year, month+1, 0, 23,59,59)
    return { from: Math.floor(from.getTime()/1000), to: Math.floor(to.getTime()/1000) }
  }, [year, month])

  const load = async () => {
    const r = await fetch(api(`/api/events?ts_from=${range.from}&ts_to=${range.to}`))
    const j = await r.json()
    setEvents(j.items || [])
  }

  useEffect(() => { load() }, [range.from, range.to])

  const prevMonth = () => {
    const d = new Date(year, month, 1); d.setMonth(d.getMonth()-1)
    setYear(d.getFullYear()); setMonth(d.getMonth())
  }
  const nextMonth = () => {
    const d = new Date(year, month, 1); d.setMonth(d.getMonth()+1)
    setYear(d.getFullYear()); setMonth(d.getMonth())
  }

  const openCreate = (date: Date) => {
    setDraftDate(date)
    setTitle('')
    setOpen(true)
  }

  const create = async (withRecord = false) => {
    const d = draftDate || new Date()
    const start_ts = Math.floor(new Date(d.getFullYear(), d.getMonth(), d.getDate(), 9,0,0).getTime()/1000)
    const res = await fetch(api('/api/events'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: title || '新規会議', start_ts, lang: 'ja' })})
    const j = await res.json()
    setOpen(false)
    if (withRecord) {
      location.href = `/recording?event_id=${j.id}&autostart=1`
    } else {
      location.href = `/meetings/${j.id}`
    }
  }

  const onOpen = (id: string) => { location.href = `/meetings/${id}` }

  const onDelete = async (id: string) => {
    if (!confirm('この会議を削除しますか？この操作は元に戻せません。')) return
    await fetch(api(`/api/events/${id}`), { method: 'DELETE' })
    // イベントリストを更新
    setEvents(prev => prev.filter(ev => ev.id !== id))
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="text-2xl font-semibold">カレンダー & DB</div>
        <div className="flex items-center gap-2">
          <button className="btn btn-ghost" onClick={prevMonth}>← 前月</button>
          <div className="opacity-80">{year}年 {month+1}月</div>
          <button className="btn btn-ghost" onClick={nextMonth}>翌月 →</button>
          <Dialog.Root open={open} onOpenChange={setOpen}>
            <Dialog.Trigger asChild>
              <button className="btn btn-primary">+ 新規イベント</button>
            </Dialog.Trigger>
            <Dialog.Portal>
              <Dialog.Overlay className="fixed inset-0 bg-black/40" />
              <Dialog.Content className="fixed inset-x-0 top-[20%] mx-auto w-[92%] max-w-[480px] card">
                <div className="font-semibold mb-2">新規イベント</div>
                <div className="space-y-2">
                  <input value={title} onChange={e=>setTitle(e.target.value)} placeholder="タイトル" className="w-full px-4 py-2 rounded-xl bg-[--panel] border border-black/10 dark:border-white/10" />
                  <div className="text-sm text-[--muted]">日付: {draftDate ? draftDate.toLocaleDateString() : new Date().toLocaleDateString()}</div>
                </div>
                <div className="mt-4 flex items-center justify-end gap-2">
                  <Dialog.Close asChild>
                    <button className="btn btn-ghost">キャンセル</button>
                  </Dialog.Close>
                  <button className="btn btn-ghost" onClick={()=>create(false)}>作成</button>
                  <button className="btn btn-primary" onClick={()=>create(true)}>作成して録音開始</button>
                </div>
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>
        </div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="order-1 lg:order-none">
          <CalendarMonth year={year} month={month} events={events} onCreate={openCreate} onOpen={onOpen} onDelete={onDelete} />
        </div>
        <div className="order-2 lg:order-none">
          <DbTable />
        </div>
      </div>
    </div>
  )
}
