import { useEffect, useRef, useState, MouseEvent } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api, ws as wsBase } from '../lib/config'
// import RecorderBar from '../components/RecorderBar'
import TranscriptList from '../components/TranscriptList'
// import SummaryPanel from '../components/SummaryPanel'
// import ScheduleWeek from '../components/ScheduleWeek'
// import * as Popover from '@radix-ui/react-popover'
// import * as Switch from '@radix-ui/react-switch'
// import ExportMenu from '../components/ExportMenu'
// import ActionList from '../components/ActionList'
import MinuteEditor from '../components/MinuteEditor'
import SummaryCard from '../components/SummaryCard'

function QASession({ eventId }: { eventId: string }) {
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(false)
  const [items, setItems] = useState<{ role: 'user'|'assistant'; text: string }[]>([])
  const ask = async () => {
    if (!eventId || !q.trim()) return
    const myQ = q.trim()
    setItems(prev => [...prev, { role: 'user', text: myQ }])
    setQ('')
    setLoading(true)
    try {
      const res = await fetch(api(`/api/events/${eventId}/qa`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ q: myQ })
      })
      const j = await res.json()
      setItems(prev => [...prev, { role: 'assistant', text: j.answer || '' }])
    } catch (e) {
      setItems(prev => [...prev, { role: 'assistant', text: 'エラーが発生しました。' }])
    } finally { setLoading(false) }
  }
  return (
    <div className="mt-4 border-t border-black/10 dark:border-white/10 pt-3">
      <div className="font-semibold mb-2">QA</div>
      <div className="grid gap-2">
        <div className="flex gap-2">
          <input
            className="flex-1 px-3 py-2 rounded-xl bg-[--panel] border border-black/10 dark:border-white/10"
            placeholder="要約や発話に基づいて質問..."
            value={q}
            onChange={(e)=> setQ(e.target.value)}
            onKeyDown={(e)=>{ if (e.key==='Enter') ask() }}
          />
          <button className="btn btn-primary" disabled={loading} onClick={ask}>{loading ? '送信中…' : '質問する'}</button>
        </div>
        <div className="grid gap-2 text-sm">
          {items.map((it, i) => (
            <div key={i} className="p-2 rounded-lg bg-[--panel] border border-black/10 dark:border-white/10">
              <div className="text-xs text-[--muted] mb-1">{it.role === 'user' ? 'あなた' : '回答'}</div>
              <div className="whitespace-pre-wrap">{it.text}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default function MeetingDetail() {
  const { id } = useParams()
  const [info, setInfo] = useState<any>(null)
  const [segments, setSegments] = useState<any[]>([])
  // 要約は SummaryCard に集約（このページでは状態を保持しない）
  const [ws, setWS] = useState<WebSocket | null>(null)
  const [token, setToken] = useState<string>('')
  const [recording, setRecording] = useState(false)
  const [artifacts, setArtifacts] = useState<any[]>([])
  const [sentChunks, setSentChunks] = useState<number>(0)
  const [serverBytes, setServerBytes] = useState<number>(0)
  const [serverFile, setServerFile] = useState<number>(0)
  const [serverIdle, setServerIdle] = useState<number>(0)
  const [serverElapsed, setServerElapsed] = useState<number>(0)
  const [participants, setParticipants] = useState<{ self: string[]; client: string[] }>({ self: [], client: [] })
  const [debugLogs, setDebugLogs] = useState<string[]>([])
  // ブラウザで再生できない場合にクリックでダウンロードさせるフラグ
  const [forceDownloadRecord, setForceDownloadRecord] = useState<boolean>(false)
  // ライブ転記（partial）の最新テキスト
  const [partialText, setPartialText] = useState<string>("")
  // サーバASRの状態: initing/ready/failed
  const [asrStatus, setAsrStatus] = useState<'initing'|'ready'|'failed'|'unknown'>('unknown')
  // 暫定: Web Speech API フォールバックの稼働状態
  const [browserASROn, setBrowserASROn] = useState<boolean>(false)
  const browserASRRef = useRef<any>(null)
  const [loadError, setLoadError] = useState<string>('')
  const [lastArtifactsAt, setLastArtifactsAt] = useState<number>(0)
  const [fetchingArtifacts, setFetchingArtifacts] = useState<boolean>(false)
  const [summarizing, setSummarizing] = useState<boolean>(false)
  const localPcm = useRef<Int16Array[]>([])
  const nav = useNavigate()
  const mediaStream = useRef<MediaStream | null>(null)
  const workletNode = useRef<any>(null)
  const stopTimingRef = useRef<{ t0: number } | null>(null)

  const debug = (() => {
    const q = new URLSearchParams(location.search)
    return !!(q.get('debug') || import.meta.env.VITE_DEBUG)
  })()

  const dlog = (msg: string) => {
    if (!debug) return
    const line = `${new Date().toLocaleTimeString()} ${msg}`
    console.log('[DEBUG]', line)
    setDebugLogs((logs) => {
      const next = [...logs, line]
      if (next.length > 200) next.shift()
      return next
    })
  }

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(api(`/api/events/${id}`))
        if (!res.ok) {
          setLoadError('このイベントIDのデータが見つかりません。新規作成してから録音を開始してください。')
          dlog(`event meta load failed: id=${id} status=${res.status}`)
          return
        }
        const j = await res.json()
        dlog(`event meta loaded: ${id}`)
        setInfo(j.event)
        setSegments(j.segments || [])
        // 要約の既存値は SummaryCard 側で再生成するためここでは保持しない
        // participants_json の初期パース
        try {
          const pj = j.event?.participants_json ? JSON.parse(j.event.participants_json) : {}
          setParticipants({ self: pj.self || [], client: pj.client || [] })
        } catch {}
      } catch (e) {
        setLoadError('サーバに接続できません。バックエンドが起動しているか確認してください。')
        dlog('event meta fetch error')
      }
    })()
  }, [id])

  const reloadEvent = async () => {
    try {
      const res = await fetch(api(`/api/events/${id}`), { cache: 'no-store' as any })
      const j = await res.json()
      setInfo(j.event)
      setSegments(j.segments || [])
      dlog('event reloaded')
    } catch (e) {
      console.warn('failed to reload event', e)
    }
  }

  // 録音自動開始は無効化（UI簡素化）

  // 再生可否の事前判定（WAV が再生不可なブラウザではダウンロードにフォールバック）
  useEffect(() => {
    try {
      const audio = document.createElement('audio')
      const support = !!audio.canPlayType && !!audio.canPlayType('audio/wav')
      if (!support) setForceDownloadRecord(true)
    } catch {}
  }, [])

  // record.wav 用の保存ファイル名
  const makeRecordFileName = () => {
    const eid = id || (location.pathname.split('/').pop() || 'event')
    const d = info?.start_ts ? new Date(info.start_ts * 1000) : new Date()
    const ts = `${d.getFullYear()}${z(d.getMonth()+1)}${z(d.getDate())}_${z(d.getHours())}${z(d.getMinutes())}${z(d.getSeconds())}`
    return `record_${eid}_${ts}.wav`
  }

  // record.wav の詳細ダウンロード（進捗ログ＋保存名付与）
  const downloadArtifact = async (a: any) => {
    try {
      const url = api(a.url)
      const filename = makeRecordFileName()
      dlog(`download: start name=${a.name} size=${a.size} url=${url} -> ${filename}`)
      const res = await fetch(url, { cache: 'no-store' as any })
      if (!res.ok || !res.body) {
        dlog(`download: fallback open, status=${res.status}`)
        const link = document.createElement('a')
        link.href = url
        link.download = filename
        document.body.appendChild(link)
        link.click()
        link.remove()
        return
      }
      const contentLength = Number(res.headers.get('Content-Length') || a.size || 0)
      const reader = res.body.getReader()
      const chunks: Uint8Array[] = []
      let received = 0
      const startedAt = Date.now()
      let lastPct = -1
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        if (value) {
          chunks.push(value)
          received += value.length
          if (contentLength > 0) {
            const pct = Math.floor((received / contentLength) * 100)
            if (pct >= lastPct + 10) { // 10%刻みでログ
              dlog(`download: progress ${pct}% (${received}/${contentLength} B)`)
              lastPct = pct
            }
          } else if (received % (256*1024) < value.length) {
            dlog(`download: received ~${Math.round(received/1024)} KB`)
          }
        }
      }
      const blob = new Blob(chunks, { type: a.mime || 'audio/wav' })
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = filename
      document.body.appendChild(link)
      link.click()
      URL.revokeObjectURL(link.href)
      link.remove()
      const ms = Date.now() - startedAt
      dlog(`download: complete ${received} B in ${ms} ms -> ${filename}`)
    } catch (e) {
      console.warn('download failed', e)
    }
  }

  // 暫定: ブラウザASR（Web Speech API）
  const startBrowserASR = async () => {
    try {
      const SR = await _ensureSpeechRecognition()
      if (browserASROn && browserASRRef.current) return
      const recog = new SR()
      recog.lang = (info?.lang || 'ja-JP').startsWith('ja') ? 'ja-JP' : (info?.lang || 'ja-JP')
      recog.continuous = true
      recog.interimResults = true
      let lastFinalTs = segments.length ? (segments[segments.length-1].end || segments[segments.length-1].start || 0) : 0
      recog.onresult = (ev: any) => {
        let interim = ''
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const res = ev.results[i]
          if (res.isFinal) {
            const text = res[0].transcript
            const s = lastFinalTs
            const e = s + 1.0
            lastFinalTs = e
            setSegments(prev => [...prev, { start: s, end: e, speaker: 'S1', text_ja: text, text_mt: '' }])
            setPartialText('')
            dlog(`browserASR final '${text}'`)
          } else {
            interim += res[0].transcript
          }
        }
        if (interim) setPartialText(interim)
      }
      recog.onerror = (e: any) => { console.warn('browserASR error', e); dlog('browserASR error') }
      recog.onend = () => { setBrowserASROn(false); dlog('browserASR end') }
      recog.start()
      browserASRRef.current = recog
      setBrowserASROn(true)
      dlog('browserASR started')
    } catch (e) {
      alert('このブラウザでは音声認識が利用できません。Chrome系でお試しください。')
    }
  }

  const stopBrowserASR = async () => {
    try {
      const r = browserASRRef.current
      if (r) { r.stop?.(); browserASRRef.current = null }
      setBrowserASROn(false)
    } catch {}
  }

  // アーティファクト一覧の定期取得
  useEffect(() => {
    let stop = false
    const tick = async () => {
      try {
        setFetchingArtifacts(true)
        const r = await fetch(api(`/api/events/${id}/artifacts`), { cache: 'no-store' as any })
        const j = await r.json()
        if (!stop) {
          setArtifacts(j.items || [])
          setLastArtifactsAt(Date.now())
          const rec = (j.items || []).find((x:any)=>x.name==='record.wav')
          dlog(`artifacts count=${(j.items||[]).length} record.wav size=${rec?rec.size:0}`)
        }
      } catch {}
      finally { setFetchingArtifacts(false) }
      if (!stop) setTimeout(tick, 3000)
    }
    tick()
    return () => { stop = true }
  }, [id])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === 'r') {
        e.preventDefault()
        recording ? stop() : start()
      } else if (e.key.toLowerCase() === 's') {
        e.preventDefault()
        // 後処理（Whisper再転記）: API が用意されていれば叩く
        fetch(api(`/api/events/${id}/postprocess`), { method: 'POST' }).catch(() => {})
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [recording, id])

  const start = async () => {
    if (loadError || !info) {
      alert('イベントが存在しない、または読み込みに失敗しました。先に新規作成してください。')
      dlog('start aborted: no event loaded')
      return
    }
    const res = await fetch(api(`/api/events/${id}/start`), { method: 'POST' })
    const j = await res.json()
    const t = j.token
    setToken(t)
    const wsUrl = wsBase(`/ws/stream?event_id=${id}&token=${t}`) || `${location.origin.replace('http','ws')}/ws/stream?event_id=${id}&token=${t}`
    const ws = new WebSocket(wsUrl)
    ws.onopen = () => { dlog('ws open'); setWS(ws) }
    ws.onerror = (e) => { dlog('ws error'); console.warn('WS error', e) }
    ws.onclose = (ev) => { dlog(`ws close code=${(ev as any).code} reason=${(ev as any).reason||''}`); setWS(null) }
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data)
      if (msg.type === 'partial') {
        // ライブの途中結果を表示
        if (typeof msg.text === 'string') {
          setPartialText(msg.text)
          if ((msg.text.length % 40) === 0) dlog(`partial '${msg.text.slice(-40)}'`)
        }
      } else if (msg.type === 'final') {
        setSegments(prev => [...prev, { start: msg.range[0], end: msg.range[1], speaker: msg.speaker, text_ja: msg.text, text_mt: msg.mt }])
        dlog(`final segment s=${msg.range?.[0]} e=${msg.range?.[1]} text='${msg.text}'`)
        // 確定したら partial はクリア
        setPartialText("")
      } else if (msg.type === 'stat') {
        if (typeof msg.bytes === 'number') setServerBytes(msg.bytes)
        if (typeof msg.file === 'number') setServerFile(msg.file)
        if (typeof msg.idle === 'number') setServerIdle(msg.idle)
        if (typeof msg.elapsed === 'number') setServerElapsed(msg.elapsed)
        if ((msg.chunks||0) % 3 === 0) dlog(`server stat: chunks=${msg.chunks} bytes=${msg.bytes} file=${msg.file} idle=${msg.idle}`)
      } else if (msg.type === 'warn' || msg.type === 'error') {
        console.warn('WS:', msg.message)
        dlog(`ws msg: ${msg.type} ${msg.message}`)
        // サーバASRの状態を簡易推定
        const m = String(msg.message||'')
        if (m.includes('ASR初期化中')) setAsrStatus('initing')
        if (m.includes('ASR初期化完了')) setAsrStatus('ready')
        if (m.includes('ASR初期化に失敗') || m.includes('ASR処理を停止しました')) setAsrStatus('failed')
      }
    }

    const ms = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, sampleRate: 48000 } })
    mediaStream.current = ms
    const ctx = new AudioContext({ sampleRate: 48000 })
    await ctx.audioWorklet.addModule('/worklet.js')
    const src = ctx.createMediaStreamSource(ms)
    const node: any = new (window as any).AudioWorkletNode(ctx, 'downsampler')
    // 再生ポリシー回避のため明示的にresume
    try {
      await ctx.resume()
    } catch {}

    node.port.onmessage = (ev: MessageEvent) => {
      if (ev.data?.type === 'chunk' && ws.readyState === ws.OPEN) {
        try {
          const buf: ArrayBuffer = ev.data.data
          // WS送信
          ws.send(buf)
          // フォールバック用にローカルへも蓄積（転送されたバッファはdetachされるのでコピー）
          try {
            const copied = new Int16Array(buf.slice(0))
            localPcm.current.push(copied)
          } catch {}
          setSentChunks((n) => n + 1)
          // 3秒ごとに進捗ログ
          setTimeout(() => {}, 0)
          if ((sentChunks + 1) % 3 === 0) dlog(`sent chunk count=${sentChunks + 1}`)
        } catch (e) {
          console.warn('WS send failed', e)
          dlog('ws send failed')
        }
      }
    }
    src.connect(node).connect(ctx.destination)
    workletNode.current = { node, ctx }
    setRecording(true)
    // ASR初期状態は不明→初期化中への遷移はwarnで通知
    setAsrStatus('unknown')
  }

  const stop = async () => {
    // ライブ途中結果は停止時にクリア
    setPartialText("")
    // 暫定: ブラウザASRも停止
    try { await stopBrowserASR() } catch {}
    dlog('stop: invoked')
    stopTimingRef.current = { t0: Date.now() }
    const wsState = ws ? ws.readyState : null
    dlog(`stop: ws state=${wsState}`)
    dlog(`stop: sentChunks=${sentChunks} serverBytes=${serverBytes} serverFile=${serverFile} serverIdle=${serverIdle}`)
    try {
      const tracks = mediaStream.current?.getTracks() || []
      dlog(`stop: media tracks=${tracks.length}`)
    } catch {}
    ws?.close()
    setWS(null)
    setRecording(false)
    dlog('stop: closing audio context')
    workletNode.current?.ctx?.close()
    mediaStream.current?.getTracks().forEach(t => t.stop())
    dlog('stop: calling postprocess')
    await fetch(api(`/api/events/${id}/stop`), { method: 'POST' }).catch(()=>{})
    dlog('stop: stop API done')
    // フォールバック: サーバ側のrecord.wavサイズが小さい/0 の場合、ローカルPCMからWAV生成してアップロード
    try {
      const rec = artifacts.find((x:any)=>x.name==='record.wav')
      const tooSmall = !rec || (rec.size||0) < 200
      dlog(`stop: server record.wav size=${rec?rec.size:NaN} tooSmall=${tooSmall}`)
      if (tooSmall && localPcm.current.length > 0) {
        const totalSamples = localPcm.current.reduce((acc,c)=>acc+c.length,0)
        dlog(`fallback: uploading local wav, chunks=${localPcm.current.length} totalSamples=${totalSamples}`)
        const wav = pcm16ToWav(localPcm.current, 16000)
        dlog(`fallback: local wav blob size=${wav.size}`)
        await fetch(api(`/api/events/${id}/upload`), {
          method: 'POST',
          headers: { 'Content-Type': 'audio/wav' },
          body: wav,
        }).catch(()=>{})
        dlog('fallback: upload done')
        // クリア
        localPcm.current = []
        dlog('fallback: local PCM cleared')
        // 直後に一覧を更新
        try {
          dlog('stop: refreshing artifacts after upload')
          const r = await fetch(api(`/api/events/${id}/artifacts`), { cache: 'no-store' as any })
          const j = await r.json()
          setArtifacts(j.items || [])
          setLastArtifactsAt(Date.now())
          const rec2 = (j.items||[]).find((x:any)=>x.name==='record.wav')
          dlog(`stop: refreshed artifacts, record.wav size=${rec2?rec2.size:NaN}`)
        } catch {}
      }
    } catch {}
    // 停止後に1回アーティファクトを更新
    try {
      dlog('stop: final artifacts refresh')
      const r = await fetch(api(`/api/events/${id}/artifacts`))
      const j = await r.json()
      setArtifacts(j.items || [])
      const rec3 = (j.items||[]).find((x:any)=>x.name==='record.wav')
      dlog(`stop: final artifacts count=${(j.items||[]).length} record.wav size=${rec3?rec3.size:NaN}`)
    } catch {}
    const elapsed = stopTimingRef.current ? (Date.now() - stopTimingRef.current.t0) : 0
    dlog(`stop: done in ${elapsed}ms`)
  }

  const remove = async (e: MouseEvent) => {
    e.preventDefault()
    if (!id) return
    if (!confirm('この会議を削除しますか？この操作は元に戻せません。')) return
    try {
      await fetch(api(`/api/events/${id}`), { method: 'DELETE' })
      nav('/meetings')
    } catch {}
  }

  return (
    <div className="space-y-6">
      <div className="card" onContextMenu={remove} title="右クリックで削除">
        {loadError && (
          <div className="mb-3 rounded-lg border border-red-200 bg-red-50 text-red-700 p-3 text-sm">
            <div className="mb-2">{loadError}</div>
            <button
              className="btn btn-primary"
              onClick={async () => {
                try {
                  const now = Math.floor(Date.now()/1000)
                  const res = await fetch(api('/api/events'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: '新規会議', start_ts: now, lang: 'ja' })})
                  const j = await res.json()
                  location.href = `/meetings/${j.id}`
                } catch {}
              }}
            >新規会議を作成</button>
            <button className="btn btn-ghost ml-2" onClick={()=> nav('/meetings')}>一覧へ戻る</button>
          </div>
        )}
        <div className="flex items-center justify-between gap-4">
          <div className="flex-1 min-w-0">
            <input
              className="w-full bg-transparent text-xl font-semibold outline-none border-b border-transparent focus:border-black/20 dark:focus:border-white/20"
              value={info?.title || ''}
              onChange={(e)=> setInfo((x:any)=> ({...x, title: e.target.value}))}
              placeholder="無題の会議"
            />
            <div className="mt-1 text-sm opacity-70 flex items-center gap-2">
              <span>{info?.start_ts ? new Date(info.start_ts*1000).toLocaleString() : ''}</span>
              <button
                className="btn btn-ghost text-xs"
                onClick={async ()=>{
                  // いまは開始時刻の保存のみ。必要に応じてUIを拡張。
                  await fetch(api(`/api/events/${id}`), {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: info?.title || '' })
                  }).catch(()=>{})
                }}
              >保存</button>
            </div>
          </div>
          <div className="shrink-0 flex items-center gap-2">
            {id && (
              <a className="btn btn-primary" href={`/recording?event_id=${id}&autostart=1`}>
                この会議で録音開始
              </a>
            )}
          </div>
        </div>
        {/* タイトル下の要約生成ボタンは削除（要約カード側のみ残す） */}
      </div>

      {/* 要約（本文） */}
      <div className="card">
        {id && <SummaryCard meetingId={id} />}
        {/* QA セクション */}
        <QASession eventId={id || ''} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 基本情報 */}
        <div className="card lg:col-span-1">
          <div className="font-semibold mb-2">基本情報</div>
          <div className="grid gap-3 text-sm">
            <div className="flex items-center gap-3">
              <div className="w-24 text-[--muted]">日時</div>
              <div>{info?.start_ts ? new Date(info.start_ts*1000).toLocaleString() : '-'}</div>
            </div>
            <div className="flex items-start gap-3">
              <div className="w-24 text-[--muted]">参加者</div>
              <div className="flex-1 grid gap-2">
                <div>
                  <div className="text-[--muted] mb-1">自社</div>
                  <input className="w-full px-3 py-2 rounded-xl bg-[--panel] border border-black/10 dark:border-white/10"
                    value={participants.self.join(', ')}
                    onChange={(e)=> setParticipants(p=>({...p, self: e.target.value.split(',').map(s=>s.trim()).filter(Boolean)}))}
                    placeholder="例: 田中, 佐藤" />
                </div>
                <div>
                  <div className="text-[--muted] mb-1">先方</div>
                  <input className="w-full px-3 py-2 rounded-xl bg-[--panel] border border-black/10 dark:border-white/10"
                    value={participants.client.join(', ')}
                    onChange={(e)=> setParticipants(p=>({...p, client: e.target.value.split(',').map(s=>s.trim()).filter(Boolean)}))}
                    placeholder="例: 鈴木, 山田" />
                </div>
                <div>
                  <button className="btn btn-ghost text-xs" onClick={async()=>{
                    const pj = JSON.stringify(participants)
                    await fetch(api(`/api/events/${id}`), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ participants_json: pj }) })
                  }}>参加者を保存</button>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* アーティファクト（基本情報の隣に配置） */}
        <div className="card">
          <div className="font-semibold mb-2">アーティファクト</div>
          {recording && (
            <div className="text-sm text-[--muted] mb-2">送信中: 約 {sentChunks}s / サーバ受信: {serverBytes}B (file {serverFile}B) / idle {serverIdle}s</div>
          )}
          <div className="text-xs text-[--muted] mb-1 flex items-center gap-2">
            <span>最終更新: {lastArtifactsAt ? new Date(lastArtifactsAt).toLocaleTimeString() : '-'}</span>
            <button className="btn btn-ghost" onClick={async()=>{
              dlog('manual refresh artifacts (top)')
              try {
                setFetchingArtifacts(true)
                const r = await fetch(api(`/api/events/${id}/artifacts`), { cache: 'no-store' as any })
                const j = await r.json()
                setArtifacts(j.items || [])
                setLastArtifactsAt(Date.now())
              } finally { setFetchingArtifacts(false) }
            }} disabled={fetchingArtifacts}>{fetchingArtifacts? '更新中…':'更新'}</button>
          </div>
          <div className="grid gap-2 text-sm max-h-[50vh] overflow-auto">
            {artifacts.length === 0 && (
              <div className="opacity-70">まだファイルはありません</div>
            )}
            {artifacts.map((a:any) => (
              <div key={a.name} className="grid gap-1">
                <a
                  className="underline"
                  href={api(a.url)}
                  target="_blank"
                  rel="noopener noreferrer"
                  download={a.name === 'record.wav' && forceDownloadRecord ? makeRecordFileName() : undefined}
                  onClick={async (e) => {
                    if (a.name === 'record.wav') {
                      e.preventDefault()
                      await downloadArtifact(a)
                    }
                  }}
                >
                  {a.name} <span className="opacity-60">({a.size} B / {(a.size/1024).toFixed(1)} KB)</span>
                </a>
                {a.name === 'record.wav' && a.size === 0 && (
                  <div className="text-xs text-[--muted]">録音中はサイズ0のことがあります。停止後に再生できます。</div>
                )}
                {a.name === 'record.wav' && a.size > 0 && (
                  <audio
                    controls
                    src={api(`${a.url}?t=${a.mtime}`)}
                    preload="metadata"
                    onLoadedMetadata={() => dlog('audio loadedmetadata (top)')}
                    onError={(e) => {
                      console.warn('audio error', e)
                      dlog('audio error (top)')
                      setForceDownloadRecord(true)
                    }}
                  />
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* アクションカードは削除 */}

      {/* 議事録エディタ */}
      {id && <MinuteEditor eventId={id} />}

      {/* 会議詳細（ライブ記録） */}
      <div className="lg:col-span-2 card">
        <div className="font-semibold mb-2">ライブ字幕</div>
          {asrStatus === 'failed' && (
            <div className="mb-2 text-xs rounded-md bg-yellow-50 border border-yellow-200 text-yellow-800 p-2">
              サーバASRの初期化に失敗しました。録音は継続しています。<br/>
              暫定措置: ブラウザ組込の音声認識でライブ表示できます（保存・要約対象外）。
              <div className="mt-1 flex items-center gap-2">
                <button className="btn btn-ghost" onClick={async()=>{ await startBrowserASR(); }}>ブラウザ認識を開始（暫定）</button>
                {browserASROn && <span className="text-[--muted]">稼働中</span>}
              </div>
            </div>
          )}
          <TranscriptList segments={(function(){
            // セグメントをキーで重複排除し、後に入ったものを優先
            const byKey = new Map<string, any>()
            for (const s of segments) {
              const key = `${(s.start||0).toFixed(2)}-${(s.end||0).toFixed(2)}-${s.speaker}-${s.text_ja || s.text}`
              byKey.set(key, s)
            }
            const uniq = Array.from(byKey.values()).sort((a:any,b:any)=> (a.start||0)-(b.start||0))
            const finals = uniq.map((s:any) => ({ t: s.start, speaker: s.speaker, text: s.text_ja || s.text, isFinal: true }))
            if (partialText) {
              // partial のタイムスタンプはサーバの経過秒 or 直近finalの終端で近似
              const last = uniq.length ? uniq[uniq.length-1] : null
              const t = (typeof serverElapsed === 'number' && serverElapsed>0) ? serverElapsed : (last ? (last.end || last.start || 0) : 0)
              const spk = last?.speaker || 'S?'
              finals.push({ t, speaker: spk, text: partialText, isFinal: false })
            }
            return finals
          })()} />
        </div>
        {/* ライブ要約パネルは削除 */}

      <div className="grid grid-cols-1 lg:grid-cols-1 gap-4">
        {/* 下部アーティファクトカードは上部へ移設済み */}
        {debug && (
          <div className="card">
            <div className="font-semibold mb-2">デバッグ</div>
            <div className="text-xs text-[--muted] mb-2">
              WS: {ws ? (ws.readyState===1 ? 'OPEN' : String(ws.readyState)) : 'null'} / 送信済み: {sentChunks} チャンク
            </div>
            <div className="max-h-[50vh] overflow-auto text-xs whitespace-pre-wrap">
              {debugLogs.map((l, i) => (<div key={i}>{l}</div>))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// PCM16の配列をWAVにエンコード（16kHz/mono）
function pcm16ToWav(chunks: Int16Array[], sampleRate: number) {
  const samples = chunks.reduce((acc, cur) => acc + cur.length, 0)
  const bytesPerSample = 2
  const headerSize = 44
  const dataSize = samples * bytesPerSample
  const buf = new ArrayBuffer(headerSize + dataSize)
  const view = new DataView(buf)

  const writeString = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i))
  }
  let offset = 0
  writeString(offset, 'RIFF'); offset += 4
  view.setUint32(offset, 36 + dataSize, true); offset += 4
  writeString(offset, 'WAVE'); offset += 4
  writeString(offset, 'fmt '); offset += 4
  view.setUint32(offset, 16, true); offset += 4 // PCM header size
  view.setUint16(offset, 1, true); offset += 2  // PCM format
  view.setUint16(offset, 1, true); offset += 2  // mono
  view.setUint32(offset, sampleRate, true); offset += 4
  view.setUint32(offset, sampleRate * bytesPerSample, true); offset += 4 // byte rate
  view.setUint16(offset, bytesPerSample, true); offset += 2 // block align
  view.setUint16(offset, 8 * bytesPerSample, true); offset += 2 // bits per sample
  writeString(offset, 'data'); offset += 4
  view.setUint32(offset, dataSize, true); offset += 4

  // write PCM16
  let pos = headerSize
  for (const chunk of chunks) {
    for (let i = 0; i < chunk.length; i++, pos += 2) {
      view.setInt16(pos, chunk[i], true)
    }
  }
  return new Blob([buf], { type: 'audio/wav' })
}

// 暫定: ブラウザのWeb Speech APIを使ったライブ認識（ASRサーバ障害時のみ）
// 使用箇所: サーバASRがfailedのときのみUIから明示起動。
// 撤去計画: sherpa_onnxモデル整備後に削除。
async function _ensureSpeechRecognition() {
  const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  if (!SR) throw new Error('SpeechRecognition not supported')
  return SR
}

// ダウンロード時の保存ファイル名（record_<id>_<yyyyMMdd_HHmmss>.wav）
function z(n: number) { return String(n).padStart(2, '0') }
