import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/config'

type Props = { eventId: string }

export default function MinuteEditor({ eventId }: Props) {
  const [md, setMd] = useState('')
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [loaded, setLoaded] = useState(false)
  const timer = useRef<number | null>(null)
  const latestValue = useRef('')

  const load = useCallback(async () => {
    try {
      const r = await fetch(api(`/api/events/${eventId}/minutes`), {
        cache: 'no-store' as any,
        credentials: 'include',
      })
      const j = await r.json()
      const text = j.md || ''
      setMd(text)
      latestValue.current = text
      setLoaded(true)
      setStatus('idle')
    } catch (err) {
      console.warn('minutes load failed', err)
      setMd('')
      latestValue.current = ''
      setStatus('error')
    }
  }, [eventId])

  useEffect(() => {
    if (eventId) {
      void load()
    }
    return () => {
      if (timer.current) {
        window.clearTimeout(timer.current)
        timer.current = null
      }
    }
  }, [eventId, load])

  const save = useCallback(
    async (body?: string) => {
      const content = body ?? latestValue.current
      try {
        setStatus('saving')
        await fetch(api(`/api/events/${eventId}/minutes`), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ md: content }),
        })
        setStatus('saved')
        window.setTimeout(() => setStatus('idle'), 1200)
      } catch (e) {
        console.error('minutes save failed', e)
        setStatus('error')
      }
    },
    [eventId]
  )

  useEffect(() => {
    latestValue.current = md
  }, [md])

  useEffect(() => {
    return () => {
      if (timer.current) {
        window.clearTimeout(timer.current)
        timer.current = null
      }
      if (latestValue.current) {
        void save(latestValue.current)
      }
    }
  }, [save])

  const onChange = (v: string) => {
    setMd(v)
    setStatus('saving')
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => save(v), 800)
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
