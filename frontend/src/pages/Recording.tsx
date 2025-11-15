import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useRecorder } from '../contexts/RecorderContext'
import MinuteEditor from '../components/MinuteEditor'
import TranscriptList from '../components/TranscriptList'

export default function Recording() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const autostart = searchParams.get('autostart') === '1'
  const eventIdParam = searchParams.get('event_id') || ''

  const {
    isRecording,
    currentEvent,
    transcripts,
    wsStats,
    audioLevel,
    audioRms,
    audioPeak,
    audioSource,
    setAudioSource,
    startRecording,
    stopRecording,
  } = useRecorder()

  const [micPermission, setMicPermission] = useState<'unknown' | 'granted' | 'denied'>('unknown')
  const [isCheckingPermission, setIsCheckingPermission] = useState(false)
  const [isSafari, setIsSafari] = useState(false)
  const [isChromeLike, setIsChromeLike] = useState(false)
  const [showScreenTip, setShowScreenTip] = useState(false)
  const transcriptsEndRef = useRef<HTMLDivElement | null>(null)
  const autostartRequestedRef = useRef(false)
  const autostartInFlightRef = useRef(false)

  useEffect(() => {
    const ua = navigator.userAgent
    const safari = /Safari\//.test(ua) && !/Chrome\//.test(ua) && !/Chromium\//.test(ua)
    const chromeFamily = /Chrome\//.test(ua) || /Chromium\//.test(ua) || /Edg\//.test(ua)
    setIsSafari(safari)
    setIsChromeLike(chromeFamily)
  }, [])

  const checkMicPermission = async () => {
    const requiresMicPermission = audioSource === 'microphone' || (audioSource === 'screen' && isSafari)
    if (!navigator.permissions || !requiresMicPermission) {
      setMicPermission('unknown')
      return
    }
    setIsCheckingPermission(true)
    try {
      const permission = await navigator.permissions.query({ name: 'microphone' as PermissionName })
      const state = permission.state === 'granted' ? 'granted' : permission.state === 'denied' ? 'denied' : 'unknown'
      setMicPermission(state)
      permission.onchange = () => {
        const nextState = permission.state === 'granted' ? 'granted' : permission.state === 'denied' ? 'denied' : 'unknown'
        setMicPermission(nextState)
      }
    } catch {
      setMicPermission('unknown')
    } finally {
      setIsCheckingPermission(false)
    }
  }

  useEffect(() => {
    checkMicPermission()
    setShowScreenTip(audioSource === 'screen' && isChromeLike && !isSafari)
  }, [audioSource, isChromeLike, isSafari])

  useEffect(() => {
    if (!autostart) return
    if (isRecording) return
    if (autostartRequestedRef.current) return
    if (autostartInFlightRef.current) return
    autostartInFlightRef.current = true
    const targetEventId = eventIdParam || currentEvent?.id
    startRecording({ eventId: targetEventId, autoCreate: !(targetEventId) })
      .then(() => {
        autostartRequestedRef.current = true
      })
      .catch((err) => {
        console.error('録音開始に失敗しました', err)
        alert('録音を開始できませんでした。マイク許可やネットワークを確認してください。')
      })
      .finally(() => {
        autostartInFlightRef.current = false
      })
  }, [autostart, currentEvent?.id, eventIdParam, isRecording, startRecording])

  useEffect(() => {
    if (transcripts.length > 0) {
      const timer = window.setTimeout(() => {
        transcriptsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
      }, 100)
      return () => window.clearTimeout(timer)
    }
  }, [transcripts])

  useEffect(() => {
    return () => {
      stopRecording().catch(() => {})
    }
  }, [stopRecording])

  const currentEventTitle = useMemo(() => {
    if (!currentEvent) return '未作成'
    return currentEvent.title || currentEvent.id
  }, [currentEvent])

  const liveSegments = useMemo(() => {
    const finals = transcripts
      .filter((t) => t.type === 'final')
      .map((t) => ({
        t: t.range?.[0] ?? 0,
        speaker: t.speaker || 'S?',
        text: t.text || '',
        mt: t.mt,
        isFinal: true,
      }))
      .sort((a, b) => a.t - b.t)
    const lastEntry = transcripts.length > 0 ? transcripts[transcripts.length - 1] : null
    if (lastEntry && lastEntry.type === 'partial') {
      const fallbackTime =
        lastEntry.range?.[0] ??
        (typeof wsStats.elapsed === 'number' ? wsStats.elapsed : finals[finals.length - 1]?.t ?? 0)
      finals.push({
        t: fallbackTime,
        speaker: lastEntry.speaker || finals[finals.length - 1]?.speaker || 'S?',
        text: lastEntry.text || '',
        isFinal: false,
      })
    }
    return finals
  }, [transcripts, wsStats.elapsed])

  const statsSpeakersRaw = wsStats.speakers
  const detectedSpeakers = useMemo(() => {
    if (Array.isArray(statsSpeakersRaw) && statsSpeakersRaw.length) {
      return statsSpeakersRaw as string[]
    }
    const set = new Set<string>()
    transcripts.forEach((t) => {
      if (t.speaker) set.add(t.speaker)
    })
    return Array.from(set)
  }, [statsSpeakersRaw, transcripts])
  const diarStatus = wsStats.diar || (detectedSpeakers.length ? 'ready' : isRecording ? 'init' : 'off')
  const diarStatusLabel =
    diarStatus === 'ready' ? '有効' : diarStatus === 'off' ? '無効' : '初期化中'
  const lastSpeaker = wsStats.last_speaker || ''

  const handleStart = async () => {
    if (isRecording) {
      alert('録音は既に進行中です')
      return
    }
    try {
      await startRecording({ eventId: eventIdParam || currentEvent?.id, autoCreate: !(eventIdParam || currentEvent?.id) })
    } catch {
      /* handled inside context */
    }
  }

  const handleStop = async () => {
    await stopRecording()
    if (currentEvent?.id) {
      navigate(`/meetings/${currentEvent.id}`)
    }
  }

  return (
    <div className="space-y-6">
      <div className="card space-y-4">
        <div className="text-sm text-[--muted]">現在のイベント</div>
        <div className="text-xl font-semibold">{currentEventTitle}</div>

        <div className="flex flex-wrap gap-4 items-center">
          <div className="space-y-1">
            <div className="text-xs text-[--muted]">入力ソース</div>
            <div className="flex gap-2">
              <button
                className={`btn ${audioSource === 'microphone' ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setAudioSource('microphone')}
                disabled={isRecording}
              >
                マイク
              </button>
              <button
                className={`btn ${audioSource === 'screen' ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setAudioSource('screen')}
                disabled={isRecording}
              >
                画面/タブ音声
              </button>
            </div>
            {micPermission === 'denied' && (
              <div className="text-xs text-red-500">マイクが拒否されています。ブラウザの設定から許可してください。</div>
            )}
            {showScreenTip && (
              <div className="text-xs text-blue-500">
                Chrome/Edge で「タブを共有」「音声を共有」を選ぶと再生中のタブ音声を録音できます。
              </div>
            )}
          </div>

          <div className="flex-1" />

          <div className="flex flex-col items-center gap-2">
            {isRecording ? (
              <button className="w-24 h-24 rounded-full bg-red-500 text-white text-xl font-bold shadow" onClick={handleStop}>
                停止
              </button>
            ) : (
              <button className="w-24 h-24 rounded-full bg-green-500 text-white text-xl font-bold shadow" onClick={handleStart}>
                開始
              </button>
            )}
            <div className="text-xs text-gray-600 dark:text-gray-300">
              音声レベル {Math.round(audioLevel * 100)}% / RMS {audioRms.toFixed(3)} / Peak {audioPeak.toFixed(3)}
            </div>
            <div className="w-64 h-3 bg-gray-200 rounded-full overflow-hidden">
              <div
                className="h-full w-full origin-left bg-gradient-to-r from-green-400 via-yellow-400 to-red-500 transition-transform duration-75"
                style={{ transform: `scaleX(${Math.max(0.05, Math.min(audioLevel, 1))})` }}
              />
            </div>
          </div>
        </div>
      </div>

      {isRecording && wsStats.elapsed && (
        <div className="card text-sm text-gray-600 dark:text-gray-300">
          録音時間: {wsStats.elapsed}s / データ {Math.round((wsStats.bytes || 0) / 1024)}KB / 無音 {wsStats.idle || 0}s
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <div className="card space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs text-[--muted]">話者分離</div>
              <div className={`text-lg font-semibold ${diarStatus === 'ready' ? 'text-green-600' : 'text-[--muted]'}`}>
                {diarStatusLabel}
              </div>
            </div>
            <div className="text-sm text-[--muted]">
              {detectedSpeakers.length > 0 ? `検出済み ${detectedSpeakers.length} 話者` : '話者検出待機中'}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {detectedSpeakers.length > 0 ? (
              detectedSpeakers.map((spk) => (
                <span key={spk} className={`badge speaker-${spk}`}>
                  {spk}
                </span>
              ))
            ) : (
              <span className="text-sm text-[--muted]">まだ話者を検出していません</span>
            )}
          </div>
          {lastSpeaker && (
            <div className="text-xs text-[--muted]">
              直近: <span className={`badge speaker-${lastSpeaker}`}>{lastSpeaker}</span>
            </div>
          )}
        </div>
        <div className="card space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs text-[--muted]">自動翻訳</div>
              <div
                className={`text-lg font-semibold ${
                  wsStats.mt === 'ready' ? 'text-green-600' : wsStats.mt === 'off' ? 'text-[--muted]' : 'text-yellow-600'
                }`}
              >
                {wsStats.mt === 'ready' ? '有効' : wsStats.mt === 'off' ? '無効' : '初期化中'}
              </div>
            </div>
            <div className="text-sm text-[--muted]">
              {wsStats.mt === 'off' ? 'CT2未設定' : 'ASR確定ごとに翻訳を試行'}
            </div>
          </div>
          <div className="text-xs text-[--muted]">
            ※ CT2 モデルを設定しない場合は無効化されます。翻訳無しでもライブ字幕は利用できます。
          </div>
        </div>
      </div>

      <div className="card min-h-[320px]">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold">ライブ字幕</h2>
          <span className="text-sm text-[--muted]">{transcripts.filter((t) => t.type === 'final').length} 発話</span>
        </div>
        {liveSegments.length === 0 ? (
          <div className="text-sm text-gray-500">まだテキストがありません。録音を開始するとリアルタイムに文字が表示されます。</div>
        ) : (
          <TranscriptList segments={liveSegments} bottomRef={transcriptsEndRef} />
        )}
      </div>

      {currentEvent?.id ? (
        <MinuteEditor eventId={currentEvent.id} />
      ) : (
        <div className="card text-sm text-[--muted]">
          録音を開始するとこの会議の議事録エディタが表示されます。録音を開始するか、既存の会議を選択してください。
        </div>
      )}
    </div>
  )
}
