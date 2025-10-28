import { useMemo } from 'react'

type Event = { id: string; title: string; start_ts: number; end_ts?: number }

function startOfMonth(d: Date) { return new Date(d.getFullYear(), d.getMonth(), 1) }
function endOfMonth(d: Date) { return new Date(d.getFullYear(), d.getMonth()+1, 0, 23,59,59) }

export default function CalendarMonth({
  year,
  month,
  events,
  onCreate,
  onOpen,
  onDelete,
}: {
  year: number
  month: number // 0-based
  events: Event[]
  onCreate?: (date: Date) => void
  onOpen?: (id: string) => void
  onDelete?: (id: string) => void
}) {
  const days = useMemo(() => {
    const first = startOfMonth(new Date(year, month, 1))
    const last = endOfMonth(new Date(year, month, 1))
    const startWeekday = first.getDay()
    const totalDays = last.getDate()
    const cells: { date: Date; inMonth: boolean }[] = []
    // prev padding
    for (let i=0;i<startWeekday;i++) {
      const d = new Date(first)
      d.setDate(d.getDate() - (startWeekday - i))
      cells.push({ date: d, inMonth: false })
    }
    for (let i=1;i<=totalDays;i++) {
      cells.push({ date: new Date(year, month, i), inMonth: true })
    }
    // next padding to complete 6 weeks
    while (cells.length % 7 !== 0 || cells.length < 42) {
      const lastDate = cells[cells.length-1].date
      const d = new Date(lastDate)
      d.setDate(d.getDate()+1)
      cells.push({ date: d, inMonth: false })
    }
    return cells
  }, [year, month])

  const eventsByDay = useMemo(() => {
    const map: Record<string, Event[]> = {}
    for (const ev of events) {
      const dt = new Date((ev.start_ts||0)*1000)
      const key = dt.toISOString().slice(0,10)
      map[key] = map[key] || []
      map[key].push(ev)
    }
    return map
  }, [events])

  return (
    <div className="border border-black/10 dark:border-white/10 rounded-2xl overflow-hidden">
      <div className="grid grid-cols-7 text-xs bg-black/5 dark:bg-white/5">
        {['日','月','火','水','木','金','土'].map((w,i)=>(<div key={i} className="p-2 text-center opacity-80">{w}</div>))}
      </div>
      <div className="grid grid-cols-7">
        {days.map(({date,inMonth},i)=>{
          const key = date.toISOString().slice(0,10)
          const list = eventsByDay[key] || []
          return (
            <div key={i} className={`min-h-[96px] border-t border-l border-black/5 dark:border-white/5 ${inMonth?'bg-transparent':'bg-black/[.02] dark:bg-white/[.02]'}`}>
              <div className="flex items-center justify-between px-2 pt-1">
                <div className={`text-xs ${inMonth? '':'opacity-50'}`}>{date.getDate()}</div>
                <button className="btn btn-ghost text-xs" onClick={()=> onCreate?.(date)}>+ 追加</button>
              </div>
              <div className="px-2 pb-1 space-y-1">
                {list.map(ev => (
                  <div 
                    key={ev.id} 
                    className="text-xs bg-blue-500/10 border border-blue-500/30 rounded px-2 py-1 truncate cursor-pointer hover:bg-blue-500/20" 
                    onClick={()=> onOpen?.(ev.id)} 
                    onContextMenu={(e) => { 
                      e.preventDefault(); 
                      onDelete?.(ev.id) 
                    }}
                    title={`${ev.title || ev.id} (右クリックで削除)`}
                  >
                    {ev.title || ev.id}
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

