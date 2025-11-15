type Event = { id: string; title: string; start: Date; end: Date; color?: string }

export default function ScheduleWeek({ events = [], onClick }: { events?: Event[]; onClick?: (id: string) => void }) {
  // Simplified static 7x time grid; no drag operations
  const hours = Array.from({ length: 16 }, (_, i) => 7 + i)
  const days = Array.from({ length: 7 }, (_, i) => i)
  return (
    <div className="border border-black/10 dark:border-white/10 rounded-2xl overflow-hidden">
      <div className="grid grid-cols-8 text-xs bg-black/5 dark:bg-white/5">
        <div className="p-2" />
        {days.map((d) => (
          <div key={d} className="p-2 text-center opacity-80">{['日','月','火','水','木','金','土'][d]}</div>
        ))}
      </div>
      <div className="grid grid-cols-8">
        <div className="bg-black/5 dark:bg-white/5">
          {hours.map(h => <div key={h} className="h-16 px-2 text-xs text-[--muted] flex items-start justify-end pt-1">{h}:00</div>)}
        </div>
        {days.map(d => (
          <div key={d} className="border-l border-black/5 dark:border-white/5">
            {hours.map(h => <div key={h} className="h-16 border-t border-black/5 dark:border-white/5" />)}
          </div>
        ))}
      </div>
    </div>
  )
}
