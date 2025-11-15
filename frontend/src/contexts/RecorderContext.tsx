import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api } from '../lib/config'
import { PcmSender } from '../audio/pcm-sender'

export type LiveTranscript = {
  type: 'partial' | 'final'
  text: string
  speaker?: string
  range?: [number, number]
  mt?: string
  id?: number
  rowId?: number
}

type WsStats = {
  chunks?: number
  bytes?: number
  file?: number
  elapsed?: number
  idle?: number
  diar?: string
  last_speaker?: string
  speakers?: string[]
  mt?: string
  [key: string]: number | string | string[] | undefined
}

type StartRecordingOptions = {
  eventId?: string
  title?: string
  autoCreate?: boolean
  autostart?: boolean
}

type RecorderContextValue = {
  isRecording: boolean
  currentEvent: any
  audioSource: 'microphone' | 'screen'
  setAudioSource: (source: 'microphone' | 'screen') => void
  transcripts: LiveTranscript[]
  wsStats: WsStats
  audioLevel: number
  audioRms: number
  audioPeak: number
  startRecording: (options?: StartRecordingOptions) => Promise<void>
  stopRecording: () => Promise<void>
}

const RecorderContext = createContext<RecorderContextValue | null>(null)

const defaultEventTitle = () => `録音 ${new Date().toLocaleString('ja-JP')}`

const isSafariBrowser = () => {
  if (typeof navigator === 'undefined') return false
  const ua = navigator.userAgent
  return /Safari\//.test(ua) && !/Chrome\//.test(ua) && !/Chromium\//.test(ua) && !/Edg\//.test(ua)
}

async function createEvent(title?: string) {
  const response = await fetch(api('/api/events'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: title || defaultEventTitle(),
      start_ts: Math.floor(Date.now() / 1000),
      lang: 'ja',
    }),
  })
  if (!response.ok) {
    throw new Error('イベントの作成に失敗しました')
  }
  return response.json()
}

async function fetchToken(eventId: string) {
  const res = await fetch(api(`/api/events/${eventId}/start`), { method: 'POST' })
  if (!res.ok) {
    throw new Error('録音トークンの取得に失敗しました')
  }
  return res.json()
}

const normalizeRangeKey = (range?: [number, number]) => (range ? `${range[0]?.toFixed(2)}-${range[1]?.toFixed(2)}` : '')

export function RecorderProvider({ children }: { children: ReactNode }) {
  const [isRecording, setIsRecording] = useState(false)
  const [currentEvent, setCurrentEvent] = useState<any>(null)
  const [audioSource, setAudioSource] = useState<'microphone' | 'screen'>('microphone')
  const [transcripts, setTranscripts] = useState<LiveTranscript[]>([])
  const [wsStats, setWsStats] = useState<WsStats>({})
  const [audioLevel, setAudioLevel] = useState(0)
  const [audioRms, setAudioRms] = useState(0)
  const [audioPeak, setAudioPeak] = useState(0)

  const wsRef = useRef<WebSocket | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const animationRef = useRef<number | null>(null)
  const pcmSenderRef = useRef<PcmSender | null>(null)

  const cleanupStream = useCallback(async () => {
    if (pcmSenderRef.current) {
      try {
        await pcmSenderRef.current.stop()
      } catch (err) {
        console.warn('pcm sender stop failed', err)
      }
      pcmSenderRef.current = null
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => {
        try {
          track.stop()
        } catch {}
      })
      streamRef.current = null
    }
    if (wsRef.current) {
      try {
        wsRef.current.close()
      } catch {}
      wsRef.current = null
    }
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current)
      animationRef.current = null
    }
    analyserRef.current = null
    try {
      sessionStorage.removeItem('recordingActive')
    } catch {}
  }, [])

  const startAudioLevelMonitoring = useCallback(() => {
    const analyser = analyserRef.current
    if (!analyser) return
    analyser.fftSize = 1024
    const bufferLength = analyser.fftSize
    const dataArray = new Float32Array(bufferLength)

    const updateAudioLevel = () => {
      analyser.getFloatTimeDomainData(dataArray)
      let sumSquares = 0
      let peak = 0
      for (let i = 0; i < bufferLength; i++) {
        const sample = dataArray[i]
        sumSquares += sample * sample
        peak = Math.max(peak, Math.abs(sample))
      }
      const rms = Math.sqrt(sumSquares / bufferLength)
      setAudioRms(rms)
      setAudioPeak(peak)
      const boosted = rms * 20 + peak * 3.5
      const sensitivityBoost = Math.pow(boosted, 0.8)
      const normalizedLevel = Math.min(sensitivityBoost, 1)
      setAudioLevel(normalizedLevel)
      if (analyserRef.current) {
        animationRef.current = requestAnimationFrame(updateAudioLevel)
      }
    }

    updateAudioLevel()
  }, [])

  const stopAudioLevelMonitoring = useCallback(() => {
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current)
      animationRef.current = null
    }
    setAudioLevel(0)
    setAudioRms(0)
    setAudioPeak(0)
  }, [])

  const getAudioStream = useCallback(async () => {
    const baseAudioConstraints: MediaTrackConstraints = {
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
    }
    if (audioSource === 'screen') {
      if (isSafariBrowser()) {
        const audioConstraints: MediaTrackConstraints = { ...baseAudioConstraints }
        try {
          let devices: MediaDeviceInfo[] = []
          if (navigator.mediaDevices.enumerateDevices) {
            devices = await navigator.mediaDevices.enumerateDevices()
          }
          const preferred = devices.find((device) => {
            if (device.kind !== 'audioinput') return false
            const label = device.label?.toLowerCase() || ''
            return label.includes('blackhole') || label.includes('black hole') || label.includes('loopback')
          })
          if (preferred?.deviceId) {
            audioConstraints.deviceId = { exact: preferred.deviceId }
          }
        } catch (err) {
          console.warn('enumerateDevices failed, using default microphone', err)
        }
        return navigator.mediaDevices.getUserMedia({
          audio: audioConstraints,
        })
      }
      const displayStream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: { ...baseAudioConstraints },
      })
      const audioTracks = displayStream.getAudioTracks()
      if (audioTracks.length === 0) {
        displayStream.getVideoTracks().forEach((track) => track.stop())
        if (!sessionStorage.getItem('screenAudioFallback')) {
          alert('選択した画面/タブに音声が含まれていないため、マイク音声へ切り替えます。Chrome/Edge では「タブを共有」「音声を共有」を選択してください。')
          sessionStorage.setItem('screenAudioFallback', '1')
        }
        return navigator.mediaDevices.getUserMedia({
          audio: { ...baseAudioConstraints },
        })
      }
      const stream = new MediaStream(audioTracks)
      displayStream.getVideoTracks().forEach((track) => track.stop())
      return stream
    }
    return navigator.mediaDevices.getUserMedia({
      audio: { ...baseAudioConstraints },
    })
  }, [audioSource])

  const updateTranscriptsFromMessage = useCallback((data: any) => {
    setTranscripts((prev) => {
      const next = [...prev]
      if (data.type === 'final-update') {
        if (typeof data.rowId === 'number') {
          const idx = next.findIndex((item) => item.rowId === data.rowId)
          if (idx >= 0) {
            next[idx] = {
              ...next[idx],
              text: data.text ?? next[idx].text,
              range: data.range ?? next[idx].range,
              mt: data.mt ?? next[idx].mt,
              speaker: data.speaker ?? next[idx].speaker,
              type: 'final',
            }
          }
        }
        return next
      }
      const isDuplicate =
        data.type === 'final' &&
        (next.some(
          (existing) =>
            existing.type === 'final' &&
            (existing.rowId && data.rowId ? existing.rowId === data.rowId : existing.text === data.text) &&
            normalizeRangeKey(existing.range) === normalizeRangeKey(data.range)
        ) ||
          (typeof data.rowId === 'number' && next.some((item) => item.rowId === data.rowId)))
      if (isDuplicate) {
        return next
      }
      if (data.type === 'partial') {
        if (next.length > 0 && next[next.length - 1].type === 'partial') {
          next[next.length - 1] = { ...data, id: Date.now() }
        } else {
          next.push({ ...data, id: Date.now() })
        }
      } else if (data.type === 'final') {
        if (next.length > 0 && next[next.length - 1].type === 'partial') {
          next[next.length - 1] = { ...data, id: Date.now(), rowId: data.rowId }
        } else {
          next.push({ ...data, id: Date.now(), rowId: data.rowId })
        }
      }
      return next.slice(-200) // limit history
    })
  }, [])

  const startRecording = useCallback(
    async (options?: StartRecordingOptions) => {
      if (isRecording) return
      try {
        let event = options?.eventId ? { id: options.eventId } : currentEvent
    if (!event) {
      event = await createEvent(options?.title)
    }
    setCurrentEvent(event)
    const { token } = await fetchToken(event.id)
    event.ws_token = token

        const stream = await getAudioStream()
        streamRef.current = stream
        setTranscripts([])
        setWsStats({})

        const wsUrl = api('/ws/stream').replace('http', 'ws') + `?event_id=${event.id}&token=${event.ws_token}`
        const ws = new WebSocket(wsUrl)
        wsRef.current = ws

        ws.onmessage = (e) => {
          try {
            const payload = JSON.parse(e.data)
            if (payload.type === 'partial' || payload.type === 'final' || payload.type === 'final-update') {
              updateTranscriptsFromMessage(payload)
            } else if (payload.type === 'stat') {
              setWsStats((prev) => ({ ...prev, ...payload }))
            } else if (payload.type === 'warn') {
              console.warn('WS warn', payload.message)
            }
          } catch (err) {
            console.warn('WS message parse error', err)
          }
        }

        ws.onerror = (err) => {
          console.error('WebSocket error', err)
        }

        const sender = new PcmSender(ws)
        await sender.start(stream)
        pcmSenderRef.current = sender
        const audioContext = sender.getContext()
        if (audioContext) {
          const analyser = audioContext.createAnalyser()
          analyserRef.current = analyser
          sender.attachAnalyser(analyser)
          startAudioLevelMonitoring()
        }

        sessionStorage.setItem('recordingActive', '1')
        setIsRecording(true)
      } catch (err) {
        console.error('録音開始エラー', err)
        await cleanupStream()
        throw err
      }
    },
    [cleanupStream, currentEvent, getAudioStream, isRecording, startAudioLevelMonitoring, updateTranscriptsFromMessage]
  )

  const stopRecording = useCallback(async () => {
    if (!isRecording) {
      return
    }
    try {
      stopAudioLevelMonitoring()
      if (currentEvent?.id) {
        try {
          await fetch(api(`/api/events/${currentEvent.id}/stop`), { method: 'POST' })
        } catch (err) {
          console.warn('stop API failed', err)
        }
      }
      if (wsRef.current) {
        try {
          wsRef.current.close()
        } catch {}
        wsRef.current = null
      }
      await cleanupStream()
    } catch (err) {
      console.error('録音停止エラー', err)
    } finally {
      setIsRecording(false)
      try {
        sessionStorage.removeItem('recordingActive')
      } catch {}
    }
  }, [cleanupStream, currentEvent, isRecording, stopAudioLevelMonitoring])

  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (isRecording) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
    }
  }, [isRecording])

  const value = useMemo<RecorderContextValue>(
    () => ({
      isRecording,
      currentEvent,
      audioSource,
      setAudioSource,
      transcripts,
      wsStats,
      audioLevel,
      audioRms,
      audioPeak,
      startRecording,
      stopRecording,
    }),
    [
      isRecording,
      currentEvent,
      audioSource,
      transcripts,
      wsStats,
      audioLevel,
      audioRms,
      audioPeak,
      startRecording,
      stopRecording,
    ]
  )

  return <RecorderContext.Provider value={value}>{children}</RecorderContext.Provider>
}

export function useRecorder(): RecorderContextValue {
  const ctx = useContext(RecorderContext)
  if (!ctx) {
    throw new Error('useRecorder must be used within RecorderProvider')
  }
  return ctx
}
