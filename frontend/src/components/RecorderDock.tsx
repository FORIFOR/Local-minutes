import { useEffect, useMemo, useState } from 'react'
import * as Popover from '@radix-ui/react-popover'
import { api } from '../lib/config'
import { navigateApp } from '../lib/navigation'

export default function RecorderDock() {
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)

  const createAndGo = async (autostart: boolean) => {
    setBusy(true)
    try {
      const now = Math.floor(Date.now()/1000)
      const r = await fetch(api('/api/events'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: 'アドホック録音', start_ts: now, lang: 'ja' }) })
      const j = await r.json()
      navigateApp(`/meetings/${j.id}${autostart ? '?autostart=1' : ''}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed right-6 bottom-6 z-40">
      <Popover.Root open={open} onOpenChange={setOpen}>
        <Popover.Trigger asChild>
          <button className="shadow-xl rounded-full w-14 h-14 flex items-center justify-center bg-[--panel] border border-black/10 dark:border-white/10 hover:shadow-2xl" aria-label="Recorder Dock">
            {busy ? '…' : '🎙️'}
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content side="top" align="end" className="card w-[240px]">
            <div className="text-sm font-semibold mb-2">レコーダー</div>
            <div className="grid gap-2">
              <button className="btn btn-primary" disabled={busy} onClick={()=>createAndGo(true)}>今すぐ録音（新規）</button>
              <button className="btn btn-ghost" disabled={busy} onClick={()=>createAndGo(false)}>イベントを作成</button>
            </div>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  )
}
