import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, apiFetch } from '../lib/config'
import { useAuth } from '../contexts/AuthContext'

interface ModelHealth {
  ok: boolean
  checks: Array<{
    name: string
    path: string
    ok: boolean
    issues: string[]
  }>
  summary: string
}

interface StatusCardProps {
  title: string
  status: 'ok' | 'warning' | 'error' | 'loading'
  description: string
  icon: string
}

function StatusCard({ title, status, description, icon }: StatusCardProps) {
  const bgColor = {
    ok: 'bg-green-50 border-green-200',
    warning: 'bg-yellow-50 border-yellow-200', 
    error: 'bg-red-50 border-red-200',
    loading: 'bg-gray-50 border-gray-200'
  }[status]

  const textColor = {
    ok: 'text-green-800',
    warning: 'text-yellow-800',
    error: 'text-red-800', 
    loading: 'text-gray-600'
  }[status]

  const statusText = {
    ok: '準備OK',
    warning: '注意',
    error: '要対応',
    loading: 'チェック中...'
  }[status]

  return (
    <div className={`p-4 rounded-xl border-2 ${bgColor}`}>
      <div className="flex items-center gap-3 mb-2">
        <span className="text-2xl">{icon}</span>
        <div>
          <h3 className="font-semibold text-gray-900">{title}</h3>
          <span className={`text-sm font-medium ${textColor}`}>{statusText}</span>
        </div>
      </div>
      <p className="text-sm text-gray-600">{description}</p>
    </div>
  )
}

export default function Home() {
  const { user } = useAuth()
  const [modelHealth, setModelHealth] = useState<ModelHealth | null>(null)
  const [recentMeetings, setRecentMeetings] = useState<any[]>([])
  const [loadingMeetings, setLoadingMeetings] = useState(true)

  useEffect(() => {
    // モデル健診チェック
    fetch(api('/api/health/models'), { credentials: 'include' })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error('failed'))))
      .then(setModelHealth)
      .catch(() => setModelHealth({ ok: false, checks: [], summary: 'チェックに失敗しました' }))

  }, [])

  useEffect(() => {
    if (!user) {
      setRecentMeetings([])
      setLoadingMeetings(false)
      return
    }
    setLoadingMeetings(true)
    apiFetch(`/api/events?limit=3`)
      .then((data) => {
        const items = Array.isArray(data) ? data : data?.items || data?.events || []
        setRecentMeetings(items || [])
      })
      .catch(() => setRecentMeetings([]))
      .finally(() => setLoadingMeetings(false))
  }, [user])

  const getASRStatus = () => {
    if (!modelHealth) return 'loading'
    const asrChecks = modelHealth.checks.filter(c => c.name.includes('ASR'))
    if (asrChecks.every(c => c.ok)) return 'ok'
    if (asrChecks.some(c => c.ok)) return 'warning'
    return 'error'
  }

  const getDiarizationStatus = () => {
    if (!modelHealth) return 'loading'
    const diarChecks = modelHealth.checks.filter(c => c.name.includes('話者分離'))
    if (diarChecks.every(c => c.ok)) return 'ok'
    if (diarChecks.some(c => c.ok)) return 'warning'
    return 'error'
  }

  return (
    <div className="space-y-6">
      {/* ヘッダー */}
      <div className="text-center">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">M4-Meet</h1>
        <p className="text-gray-600">まずは<strong>録音をはじめる</strong>を押してください。</p>
        <p className="text-sm text-gray-500">すべてローカルで処理されます。インターネットは使いません。</p>
      </div>

      {/* ステータスカード */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <StatusCard
          title="マイク入力"
          status="ok"
          description="マイクアクセスが許可されています"
          icon="🎤"
        />
        <StatusCard
          title="ASR（音声認識）"
          status={getASRStatus()}
          description="SenseVoice による日本語音声認識"
          icon="🗣️"
        />
        <StatusCard
          title="リアルタイム話者分離"
          status={getDiarizationStatus()}
          description="話者を自動で識別・分離します"
          icon="👥"
        />
        <StatusCard
          title="停止後バッチ"
          status="ok"
          description="無効（推奨） - 必要時のみ有効化"
          icon="⚡"
        />
      </div>

      {/* 録音開始ボタン */}
      <div className="text-center">
        <Link
          to="/recording"
          className="inline-flex items-center gap-2 px-8 py-4 bg-blue-600 text-white font-semibold rounded-xl hover:bg-blue-700 transition-colors"
        >
          <span className="text-xl">🎙️</span>
          録音をはじめる
        </Link>
      </div>

      {/* 最近の会議 */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-lg font-semibold mb-4">最近の会議</h2>
        {loadingMeetings ? (
          <p className="text-sm text-gray-500">読み込み中...</p>
        ) : recentMeetings.length > 0 ? (
          <div className="space-y-3">
            {recentMeetings.map((meeting) => (
              <Link
                key={meeting.id}
                to={`/meetings/${meeting.id}`}
                className="block p-3 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
              >
                <div className="flex justify-between items-start">
                  <div>
                    <h3 className="font-medium text-gray-900">{meeting.title}</h3>
                    <p className="text-sm text-gray-500">
                      {new Date(meeting.started_at || meeting.start_ts * 1000).toLocaleDateString('ja-JP')}
                    </p>
                  </div>
                  <span className="text-xs text-gray-400">
                    {meeting.duration ? `${Math.round(meeting.duration / 60)}分` : ''}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <p className="text-gray-500 text-center py-4">まだ会議がありません</p>
        )}
      </div>

      {/* モデル健診サマリー */}
      {modelHealth && (
        <div className="bg-gray-50 rounded-xl p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-600">モデル状態: {modelHealth.summary}</span>
            <Link 
              to="/settings" 
              className="text-sm text-blue-600 hover:text-blue-700"
            >
              詳細設定 →
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}
