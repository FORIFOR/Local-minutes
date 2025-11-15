import type { RefObject } from 'react'

type Segment = { t: number; speaker: string; text: string; mt?: string; isFinal?: boolean }

function formatTime(t: number) {
  const ms = Math.floor((t % 1) * 10)
  const s = Math.floor(t) % 60
  const m = Math.floor(t / 60) % 60
  const h = Math.floor(t / 3600)
  const pad = (n: number, w = 2) => n.toString().padStart(w, '0')
  return `${pad(h)}:${pad(m)}:${pad(s)}.${ms}`
}

export function SegmentRow({ t, speaker, text, mt, isFinal }: Segment) {
  const speakerKey = `speaker-${speaker}`
  const rowClass = isFinal ? speakerKey : 'seg-partial'
  return (
    <div className={`seg grid grid-cols-[72px_1fr] gap-3 ${rowClass}`}>
      <div className="text-xs text-[--muted] mt-0.5">{formatTime(t)}</div>
      <div>
        <span className={`badge ${speakerKey}`}>{speaker}</span>
        {!isFinal && <span className="live-chip">LIVE</span>}
        <span className="ml-2">{text}</span>
        {mt && <div className="text-xs text-[--muted] mt-1">{mt}</div>}
      </div>
    </div>
  )
}

export default function TranscriptList({
  segments,
  bottomRef,
}: {
  segments: Segment[]
  bottomRef?: RefObject<HTMLDivElement>
}) {
  return (
    <div className="space-y-2 max-h-[50vh] overflow-auto">
      {segments.map((s, i) => (
        <SegmentRow key={i} {...s} />
      ))}
      {bottomRef && <div ref={bottomRef} />}
    </div>
  )
}
