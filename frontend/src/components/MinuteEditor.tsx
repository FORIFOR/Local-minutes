import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/config'

type Props = { eventId: string }

export default function MinuteEditor({ eventId }: Props) {
  const [md, setMd] = useState('')
  const [status, setStatus] = useState<'idle'|'saving'|'saved'|'error'>('idle')
  const [loaded, setLoaded] = useState(false)
  const timer = useRef<number | null>(null)

  const load = async () => {
    const r = await fetch(api(`/api/events/${eventId}/minutes`), { cache: 'no-store' as any })
    const j = await r.json()
    setMd(j.md || '')
    setLoaded(true)
  }

  useEffect(() => { if (eventId) load() }, [eventId])

  const save = async () => {
    try {
      setStatus('saving')
      await fetch(api(`/api/events/${eventId}/minutes`), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ md }) })
      setStatus('saved')
      setTimeout(() => setStatus('idle'), 1200)
    } catch (e) {
      setStatus('error')
    }
  }

  const onChange = (v: string) => {
    setMd(v)
    setStatus('saving')
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(save, 800)
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-2">
        <div className="font-semibold">議事録</div>
        <div className="text-xs text-[--muted]">
          {status === 'saving' && '保存中…'}
          {status === 'saved' && '保存済み'}
          {status === 'error' && '保存に失敗'}
        </div>
      </div>
      <textarea
        className="w-full min-h-[240px] leading-6 bg-[--panel] outline-none rounded-xl p-3 border border-black/10 dark:border-white/10"
        placeholder={`# タイトル\n\n## 注意事項\n- ...\n\n## 基本情報\n- 会議の目的: \n- アジェンダ: \n\n## 決定事項\n- [ ] ...\n\n## アクション\n- [ ] 担当: 期限: 内容\n\n## 添付/資料リンク\n- URL: \n\n## メモ\n- ...`}
        value={md}
        onChange={(e)=> onChange(e.target.value)}
      />
    </div>
  )
}

