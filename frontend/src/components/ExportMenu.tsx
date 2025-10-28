import * as Popover from '@radix-ui/react-popover'
import { api } from '../lib/config'

type Props = { eventId: string }

async function fetchContent(url: string): Promise<string> {
  const r = await fetch(url)
  const j = await r.json()
  return j.content || ''
}

function downloadText(filename: string, text: string, mime = 'text/plain;charset=utf-8') {
  const blob = new Blob([text], { type: mime })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  document.body.appendChild(a)
  a.click()
  URL.revokeObjectURL(a.href)
  a.remove()
}

export default function ExportMenu({ eventId }: Props) {
  const run = async (kind: 'srt' | 'vtt' | 'rttm' | 'ics') => {
    const url = api(`/download.${kind}?id=${eventId}`)
    const content = await fetchContent(url)
    const name = `${eventId}.${kind}`
    const mime = kind === 'ics' ? 'text/calendar' : 'text/plain'
    downloadText(name, content, mime)
  }
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button className="btn btn-ghost" aria-haspopup="menu">エクスポート ▾</button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="bottom" align="start" className="card p-2">
          <div className="grid gap-1 text-sm">
            <button className="underline text-left" onClick={()=>run('srt')}>SRT</button>
            <button className="underline text-left" onClick={()=>run('vtt')}>VTT</button>
            <button className="underline text-left" onClick={()=>run('rttm')}>RTTM</button>
            <button className="underline text-left" onClick={()=>run('ics')}>ICS</button>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

