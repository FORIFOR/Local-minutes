import { useState, useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../lib/config'

interface LiveTranscript {
  type: 'partial' | 'final'
  text: string
  speaker?: string
  range?: [number, number]
  mt?: string
  id?: number
}

export default function Recording() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const eventIdParam = searchParams.get('event_id') || ''
  const [isRecording, setIsRecording] = useState(false)
  const [currentEvent, setCurrentEvent] = useState<any>(null)
  const [audioSource, setAudioSource] = useState('microphone')
  const [transcripts, setTranscripts] = useState<LiveTranscript[]>([])
  const [wsStats, setWsStats] = useState<any>({})
  const [micPermission, setMicPermission] = useState<'unknown' | 'granted' | 'denied'>('unknown')
  const [isCheckingPermission, setIsCheckingPermission] = useState(false)
  const [audioLevel, setAudioLevel] = useState(0)
  const [isSafari, setIsSafari] = useState(false)
  const [isChromeLike, setIsChromeLike] = useState(false) // Chrome/Edge/Chromium 系
  const [showScreenTip, setShowScreenTip] = useState(false)
  const noAudioAlertShownRef = useRef(false)
  
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const animationRef = useRef<number | null>(null)
  const transcriptsEndRef = useRef<HTMLDivElement | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const workletNodeRef = useRef<AudioWorkletNode | null>(null)

  useEffect(() => {
    // autostart パラメータがあれば自動開始
    if (searchParams.get('autostart') === '1') {
      handleStart()
    }

    // マイク権限の初期チェック
    checkMicPermission()
    // ブラウザ判定
    try {
      const ua = navigator.userAgent
      const isSafariUA = /Safari\//.test(ua) && !/Chrome\//.test(ua) && !/Chromium\//.test(ua)
      const isChromeUA = /Chrome\//.test(ua) || /Chromium\//.test(ua) || /Edg\//.test(ua)
      setIsSafari(isSafariUA)
      setIsChromeLike(isChromeUA)
      // 画面キャプチャのヒントは Chrome 系で screen を選んだときに表示
      setShowScreenTip(false)
    } catch {}
  }, [searchParams])

  const checkMicPermission = async () => {
    if (!navigator.permissions || audioSource !== 'microphone') {
      setMicPermission('unknown')
      return
    }
    
    setIsCheckingPermission(true)
    try {
      const permission = await navigator.permissions.query({ name: 'microphone' as PermissionName })
      setMicPermission(permission.state === 'granted' ? 'granted' : 
                      permission.state === 'denied' ? 'denied' : 'unknown')
      
      // 権限状態の変更を監視
      permission.onchange = () => {
        setMicPermission(permission.state === 'granted' ? 'granted' : 
                        permission.state === 'denied' ? 'denied' : 'unknown')
      }
    } catch (error) {
      console.log('権限チェックをスキップ:', error)
      setMicPermission('unknown')
    } finally {
      setIsCheckingPermission(false)
    }
  }

  // 入力ソース変更時にマイク権限を再チェック
  useEffect(() => {
    checkMicPermission()
    // Chrome系でタブ音声を案内
    if (audioSource === 'screen' && isChromeLike) {
      setShowScreenTip(true)
    } else {
      setShowScreenTip(false)
    }
  }, [audioSource])

  // 文字起こし結果更新時の自動スクロール
  useEffect(() => {
    if (transcripts.length > 0) {
      setTimeout(() => {
        transcriptsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
      }, 100)
    }
  }, [transcripts])

  // コンポーネント破棄時やページ離脱時のクリーンアップ
  useEffect(() => {
    const cleanup = () => {
      if (isRecording) {
        console.log('🚨 緊急停止: ページ離脱によるマイク停止')
        handleStop()
      }
    }

    // ページ離脱時のクリーンアップ
    window.addEventListener('beforeunload', cleanup)
    
    // コンポーネント破棄時のクリーンアップ
    return () => {
      window.removeEventListener('beforeunload', cleanup)
      cleanup()
    }
  }, [isRecording])

  const startAudioLevelMonitoring = () => {
    const analyser = analyserRef.current
    if (!analyser) return

    const dataArray = new Uint8Array(analyser.frequencyBinCount)
    
    const updateAudioLevel = () => {
      analyser.getByteFrequencyData(dataArray)
      const sum = dataArray.reduce((acc, value) => acc + value, 0)
      const average = sum / dataArray.length
      const normalizedLevel = Math.min(average / 128, 1)
      setAudioLevel(normalizedLevel)
      
      if (analyserRef.current) {
        animationRef.current = requestAnimationFrame(updateAudioLevel)
      }
    }
    
    updateAudioLevel()
  }

  const stopAudioLevelMonitoring = () => {
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current)
      animationRef.current = null
    }
    setAudioLevel(0)
  }

  const handleStart = async () => {
    try {
      console.log('🎤 録音開始処理開始')
      
      // 1. 既存イベントが指定されている場合はそれを使用、なければ作成
      let event: any
      if (eventIdParam) {
        console.log('📝 既存イベントで録音開始:', eventIdParam)
        event = { id: eventIdParam }
      } else {
        console.log('📝 イベント作成中...')
        const response = await fetch(api('/api/events'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: `録音 ${new Date().toLocaleString('ja-JP')}`,
            start_ts: Math.floor(Date.now() / 1000),
            lang: 'ja'
          })
        })
        event = await response.json()
        console.log('✅ イベント作成完了:', event.id)
      }

      // 2. イベント開始してトークン取得
      console.log('🔑 トークン取得中...', event.id)
      const startResponse = await fetch(api(`/api/events/${event.id}/start`), { method: 'POST' })
      const { token } = await startResponse.json()
      event.ws_token = token
      console.log('✅ トークン取得完了:', token)

      setCurrentEvent(event)

      // 3. 音声入力取得
      console.log('🎧 音声入力取得中...', audioSource)
      let stream: MediaStream
      if (audioSource === 'screen') {
        // 画面キャプチャ（音声付き）
        // Safari は多くの環境で音声トラックが供給されないため、実質マイクにフォールバック
        const displayStream = await navigator.mediaDevices.getDisplayMedia({ 
          video: true,  // videoはtrueである必要がある
          audio: {
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false
          }
        })

        // 音声トラックのみを取得
        const audioTracks = displayStream.getAudioTracks()
        if (audioTracks.length === 0) {
          // 音声なしの場合はマイクと併用
          console.log('⚠️ 画面に音声がありません。マイク音声と併用します。')
          displayStream.getVideoTracks().forEach(track => track.stop())

          // マイク音声を取得して使用
          stream = await navigator.mediaDevices.getUserMedia({ 
            audio: {
              echoCancellation: false,
              noiseSuppression: false,
              autoGainControl: false
            } 
          })
          if (!noAudioAlertShownRef.current) {
            const msgSafari = 'Safariでは画面共有に音声が含まれないため、マイク音声で録音します。\n\n画面(タブ)の音声を録音したい場合は Chrome/Edge をご利用ください。'
            const msgChrome = '選択した画面に音声が含まれていません。マイク音声で録音します。\n\nタブ音声を録音するには：\n1. Chrome/Edge の「タブ」を選択\n2. 「音声を共有」にチェック\n3. 音声が再生されているタブを選択'
            alert(isSafari ? msgSafari : msgChrome)
            noAudioAlertShownRef.current = true
          }
        } else {
          // 音声のみのStreamを作成
          stream = new MediaStream(audioTracks)

          // ビデオトラックは停止（音声のみ使用）
          displayStream.getVideoTracks().forEach(track => track.stop())
          console.log('✅ 画面音声を取得しました:', audioTracks.map(t => t.label))
        }
      } else {
        // マイク入力
        stream = await navigator.mediaDevices.getUserMedia({ 
          audio: {
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false
          } 
        })
      }
      streamRef.current = stream
      console.log('✅ 音声入力取得完了:', stream.getTracks().map(t => `${t.kind}:${t.label}`))

      // 4. WebSocket接続
      const wsUrl = api('/ws/stream').replace('http', 'ws') + `?event_id=${event.id}&token=${event.ws_token}`
      console.log('🔗 WebSocket接続中...', wsUrl)
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        console.log('✅ WebSocket接続成功')
      }

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          console.log('📨 WebSocketメッセージ受信:', data.type, data.text?.substring(0, 50) || data.message)
          
          if (data.type === 'partial' || data.type === 'final') {
            setTranscripts(prev => {
              const newTranscripts = [...prev]
              
              // 重複チェック：同じテキストと近い時間範囲の場合はスキップ
              const isDuplicate = data.type === 'final' && newTranscripts.some(existing => 
                existing.type === 'final' && 
                existing.text === data.text &&
                existing.range && data.range &&
                Math.abs(existing.range[0] - data.range[0]) < 2.0 // 2秒以内の重複をチェック
              )
              
              if (isDuplicate) {
                console.log('📝 重複テキストをスキップ:', data.text)
                return newTranscripts
              }
              
              if (data.type === 'partial') {
                // 部分結果: 末尾のpartialを置き換え、または新規追加
                if (newTranscripts.length > 0 && newTranscripts[newTranscripts.length - 1].type === 'partial') {
                  newTranscripts[newTranscripts.length - 1] = { ...data, id: Date.now() }
                } else {
                  newTranscripts.push({ ...data, id: Date.now() })
                }
              } else {
                // 確定結果: 末尾のpartialを置き換えるか、新規追加
                if (newTranscripts.length > 0 && newTranscripts[newTranscripts.length - 1].type === 'partial') {
                  newTranscripts[newTranscripts.length - 1] = { ...data, id: Date.now() }
                } else {
                  newTranscripts.push({ ...data, id: Date.now() })
                }
              }
              
              return newTranscripts
            })
          } else if (data.type === 'stat') {
            setWsStats(data)
          } else if (data.type === 'warn') {
            console.warn('⚠️ サーバーからの警告:', data.message)
          }
        } catch (error) {
          console.error('❌ WebSocketメッセージの解析に失敗:', error)
        }
      }

      ws.onerror = (error) => {
        console.error('❌ WebSocket接続エラー:', error)
      }

      ws.onclose = (event) => {
        console.log('🔌 WebSocket接続が閉じられました:', event.code, event.reason)
      }

      // 5. 音声録音開始
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: 'audio/webm;codecs=opus'
      })
      mediaRecorderRef.current = mediaRecorder

      // オーディオワークレットで16kHz/monoに変換してWebSocketに送信
      const audioContext = new AudioContext()
      audioContextRef.current = audioContext
      const source = audioContext.createMediaStreamSource(stream)
      
      // 音声レベル分析用のAnalyserNode
      const analyser = audioContext.createAnalyser()
      analyser.fftSize = 256
      analyserRef.current = analyser
      source.connect(analyser)
      
      // 音声レベル監視を開始
      startAudioLevelMonitoring()
      
      await audioContext.audioWorklet.addModule('/worklet.js')
      const workletNode = new AudioWorkletNode(audioContext, 'downsampler')
      workletNodeRef.current = workletNode
      
      workletNode.port.onmessage = (e) => {
        if (ws.readyState === WebSocket.OPEN && e.data.type === 'chunk') {
          console.log('🎵 音声データ送信:', e.data.data.byteLength, 'bytes')
          ws.send(e.data.data)
        } else {
          console.warn('⚠️ WebSocket未接続のため音声データを破棄:', ws.readyState)
        }
      }

      source.connect(workletNode)
      // workletNode.connect(audioContext.destination) // ループバック防止のためコメントアウト

      console.log('🎤 録音開始完了！')
      setIsRecording(true)

    } catch (error) {
      console.error('録音開始エラー:', error)
      
      let errorMessage = '録音を開始できませんでした。'
      
      if (error instanceof DOMException) {
        switch (error.name) {
          case 'NotAllowedError':
            errorMessage += '\n\nマイクアクセスが拒否されました。\n• ブラウザの設定でマイクを許可してください\n• システム設定でブラウザのマイクアクセスを確認してください'
            break
          case 'NotFoundError':
            errorMessage += '\n\nマイクが見つかりませんでした。\n• マイクが接続されているか確認してください\n• 他のアプリがマイクを使用していないか確認してください'
            break
          case 'NotSupportedError':
            errorMessage += '\n\nお使いのブラウザまたは環境では音声録音がサポートされていません。'
            break
          case 'NotReadableError':
            errorMessage += '\n\nマイクにアクセスできませんでした。\n• 他のアプリがマイクを使用していないか確認してください\n• マイクを再接続してみてください'
            break
          case 'OverconstrainedError':
            errorMessage += '\n\n指定された音声設定が利用できませんでした。\n• 別の入力ソースを試してください'
            break
          default:
            errorMessage += `\n\nエラーの詳細: ${error.message}`
        }
      } else {
        errorMessage += `\n\nエラーの詳細: ${error}`
      }
      
      alert(errorMessage)
    }
  }

  const handleStop = async () => {
    try {
      console.log('🛑 録音停止処理開始')
      
      // 音声レベル監視停止
      stopAudioLevelMonitoring()
      analyserRef.current = null
      console.log('✅ 音声レベル監視停止')

      // WebSocket切断
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
        console.log('✅ WebSocket切断')
      }

      // MediaRecorder停止
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop()
        mediaRecorderRef.current = null
        console.log('✅ MediaRecorder停止')
      }

      // AudioWorkletNode停止
      if (workletNodeRef.current) {
        workletNodeRef.current.disconnect()
        workletNodeRef.current = null
        console.log('✅ AudioWorkletNode停止')
      }

      // AudioContext停止
      if (audioContextRef.current) {
        await audioContextRef.current.close()
        audioContextRef.current = null
        console.log('✅ AudioContext停止')
      }

      // 音声ストリーム停止（マイクオフ）
      if (streamRef.current) {
        console.log('🎤 マイクをオフにしています...')
        streamRef.current.getTracks().forEach(track => {
          console.log(`📴 音声トラック停止: ${track.kind} (${track.label}) - enabled: ${track.enabled} -> false`)
          track.enabled = false  // まず無効化
          track.stop()           // そして停止
        })
        streamRef.current = null
        console.log('✅ マイク停止完了')
        
        // マイク停止後の状態確認
        setTimeout(() => {
          if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
            navigator.mediaDevices.enumerateDevices().then(devices => {
              const audioInputs = devices.filter(device => device.kind === 'audioinput')
              console.log('🔍 マイク停止後のデバイス状態:', audioInputs.map(d => ({
                label: d.label,
                deviceId: d.deviceId.substring(0, 8) + '...'
              })))
            })
          }
        }, 500)
      }

      setIsRecording(false)
      console.log('🛑 録音停止処理完了')

      // イベント停止API呼び出し
      if (currentEvent) {
        await fetch(api(`/api/events/${currentEvent.id}/stop`), {
          method: 'POST'
        })
        
        // 会議詳細ページに遷移
        navigate(`/meetings/${currentEvent.id}`)
      }

    } catch (error) {
      console.error('録音停止エラー:', error)
    }
  }

  const getSourceLabel = () => {
    switch (audioSource) {
      case 'microphone': return 'マイク'
      case 'blackhole': return 'システム音声（BlackHole等）'
      case 'screen': return 'タブの音声（画面キャプチャ）'
      default: return 'マイク'
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* 録音コントロール */}
      <div className="text-center space-y-4">
        <h1 className="text-2xl font-bold text-gray-900">録音</h1>
        
        {/* 入力ソース選択 */}
        <div className="flex justify-center items-center gap-4">
          <select
            value={audioSource}
            onChange={(e) => setAudioSource(e.target.value)}
            disabled={isRecording}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="microphone">マイク</option>
            <option value="blackhole">システム音声（BlackHole等）</option>
            {isSafari ? (
              <option value="screen" disabled>タブの音声（Safariは非対応）</option>
            ) : (
              <option value="screen">タブの音声（画面キャプチャ）</option>
            )}
          </select>
          
          {/* マイク権限状態表示 */}
          {audioSource === 'microphone' && (
            <div className="flex items-center gap-2">
              {isCheckingPermission ? (
                <span className="text-sm text-gray-500">チェック中...</span>
              ) : (
                <div className={`flex items-center gap-1 text-sm px-2 py-1 rounded ${
                  micPermission === 'granted' ? 'bg-green-100 text-green-700' :
                  micPermission === 'denied' ? 'bg-red-100 text-red-700' :
                  'bg-yellow-100 text-yellow-700'
                }`}>
                  <span>
                    {micPermission === 'granted' ? '✅' :
                     micPermission === 'denied' ? '❌' : '⚠️'}
                  </span>
                  <span>
                    {micPermission === 'granted' ? 'マイク許可済み' :
                     micPermission === 'denied' ? 'マイク拒否' :
                     'マイク権限不明'}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ブラウザ別の補足メッセージ */}
        {audioSource === 'screen' && (
          <div className="mt-2 text-xs text-gray-600 max-w-md mx-auto">
            {isSafari ? (
              <div className="rounded-md border border-yellow-200 bg-yellow-50 text-yellow-800 p-2">
                Safariではタブ/画面共有に音声が含まれません。タブ音声を録音する場合は Chrome/Edge をご利用ください。
              </div>
            ) : showScreenTip ? (
              <div className="rounded-md border border-blue-200 bg-blue-50 text-blue-800 p-2">
                タブ音声を録音するには、共有ダイアログで「タブ」を選び「音声を共有」をチェックして、音声が再生されているタブを選択してください。
              </div>
            ) : null}
          </div>
        )}

        {/* 録音ボタン */}
        <div className="flex flex-col items-center gap-4">
          {isRecording ? (
            <button
              onClick={handleStop}
              className="w-32 h-32 rounded-full bg-red-500 hover:bg-red-600 text-white font-bold text-xl transition-colors shadow-lg"
            >
              ■ 停止
            </button>
          ) : (
            <button
              onClick={handleStart}
              className="w-32 h-32 rounded-full bg-blue-500 hover:bg-blue-600 text-white font-bold text-xl transition-colors shadow-lg"
            >
              ● 開始
            </button>
          )}
          
          {/* 音声レベル表示 */}
          {isRecording && (
            <div className="flex flex-col items-center gap-2">
              <div className="w-64 h-4 bg-gray-200 rounded-full overflow-hidden">
                <div 
                  className="h-full bg-gradient-to-r from-green-400 via-yellow-400 to-red-500 transition-all duration-75"
                  style={{ width: `${audioLevel * 100}%` }}
                />
              </div>
              <span className="text-xs text-gray-600">音声レベル</span>
            </div>
          )}
        </div>

        <p className="text-sm text-gray-600">
          {isRecording 
            ? `${getSourceLabel()}から録音中... 話し終わると数秒で文字が出ます。`
            : `入力ソース: ${getSourceLabel()}`
          }
        </p>
      </div>

      {/* 録音統計 */}
      {isRecording && wsStats.elapsed && (
        <div className="bg-gray-50 rounded-lg p-4">
          <div className="text-center text-sm text-gray-600">
            録音時間: {wsStats.elapsed}秒 | 
            データ: {Math.round((wsStats.bytes || 0) / 1024)}KB |
            {wsStats.idle ? ` 無音: ${wsStats.idle}秒` : ''}
          </div>
        </div>
      )}

      {/* ライブ字幕 */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 min-h-64">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">ライブ字幕</h2>
          {transcripts.length > 0 && (
            <span className="text-sm text-gray-500">
              {transcripts.filter(t => t.type === 'final').length} 発話
            </span>
          )}
        </div>
        
        {transcripts.length > 0 ? (
          <div className="space-y-3 max-h-96 overflow-y-auto">
            {transcripts.map((transcript) => (
              <div 
                key={transcript.id || transcript.text}
                className={`p-3 rounded-lg transition-all duration-200 ${
                  transcript.type === 'final' 
                    ? 'bg-green-50 border border-green-200' 
                    : 'bg-yellow-50 border border-yellow-200 animate-pulse'
                }`}
              >
                <div className="flex items-start gap-3">
                  <span className={`font-medium text-sm px-2 py-1 rounded ${
                    transcript.type === 'final' 
                      ? 'bg-green-100 text-green-700'
                      : 'bg-yellow-100 text-yellow-700'
                  }`}>
                    {transcript.speaker || 'S1'}
                  </span>
                  <div className="flex-1">
                    <p className="text-gray-900 leading-relaxed">{transcript.text}</p>
                    {transcript.mt && (
                      <p className="text-sm text-gray-600 mt-1 italic border-l-2 border-gray-300 pl-2">
                        {transcript.mt}
                      </p>
                    )}
                    {transcript.range && transcript.type === 'final' && (
                      <p className="text-xs text-gray-400 mt-1">
                        {transcript.range[0].toFixed(1)}s - {transcript.range[1].toFixed(1)}s
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {transcript.type === 'partial' && (
                      <span className="text-xs text-yellow-600 font-medium">処理中...</span>
                    )}
                    {transcript.type === 'final' && (
                      <span className="text-xs text-green-600">✓</span>
                    )}
                  </div>
                </div>
              </div>
            ))}
            <div ref={transcriptsEndRef} />
          </div>
        ) : (
          <div className="text-center text-gray-500 py-8">
            {isRecording 
              ? '話してください。音声が検出されると文字起こしが表示されます。'
              : '録音を開始すると、ここにライブ字幕が表示されます。'
            }
          </div>
        )}
      </div>

      {/* 操作ガイド */}
      <div className="bg-blue-50 rounded-lg p-4">
        <h3 className="font-medium text-blue-900 mb-2">使い方</h3>
        <ul className="text-sm text-blue-800 space-y-1">
          <li>• 入力ソースを選んで「開始」ボタンを押してください</li>
          <li>• 話し終わると数秒で文字が表示されます</li>
          <li>• 終わったら「停止」ボタンを押してください。保存は自動です</li>
          <li>• <strong>システム音声全体を録音：</strong>BlackHole等の仮想音声デバイスをインストールし、システム出力を設定</li>
          <li>• <strong>特定のタブ音声：</strong>画面キャプチャでタブ選択時に「音声を共有」をチェック</li>
        </ul>
      </div>
    </div>
  )
}
