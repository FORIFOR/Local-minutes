import { useState, useEffect } from 'react'
import { api } from '../lib/config'

interface ModelHealth {
  ok: boolean
  checks: Array<{
    name: string
    path: string
    ok: boolean
    issues: string[]
    inputs?: Array<{ name: string; shape: any[] }>
    outputs?: Array<{ name: string; shape: any[] }>
  }>
  summary: string
}

export default function Settings() {
  const [modelHealth, setModelHealth] = useState<ModelHealth | null>(null)
  const [isChecking, setIsChecking] = useState(false)
  const [mode, setMode] = useState<'simple' | 'advanced'>('simple')

  const checkModels = async () => {
    setIsChecking(true)
    try {
      const response = await fetch(api('/api/health/models'))
      const data = await response.json()
      setModelHealth(data)
    } catch (error) {
      console.error('モデル健診エラー:', error)
    } finally {
      setIsChecking(false)
    }
  }

  useEffect(() => {
    checkModels()
  }, [])

  const getStatusIcon = (ok: boolean) => ok ? '✅' : '❌'
  const getStatusColor = (ok: boolean) => ok ? 'text-green-700' : 'text-red-700'

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-gray-900">モデル & 設定</h1>
        <div className="flex gap-2">
          <button
            onClick={() => setMode('simple')}
            className={`px-3 py-1 rounded text-sm font-medium ${
              mode === 'simple' 
                ? 'bg-blue-500 text-white' 
                : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
            }`}
          >
            最小モード
          </button>
          <button
            onClick={() => setMode('advanced')}
            className={`px-3 py-1 rounded text-sm font-medium ${
              mode === 'advanced' 
                ? 'bg-blue-500 text-white' 
                : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
            }`}
          >
            詳細モード
          </button>
        </div>
      </div>

      {mode === 'simple' && (
        <div className="space-y-6">
          {/* 最小モード */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="text-lg font-semibold mb-4">基本設定</h2>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  ASR（音声認識）
                </label>
                <div className="bg-gray-50 p-3 rounded-lg">
                  <p className="text-sm text-gray-600">SenseVoice INT8（選択済み）</p>
                  <p className="text-xs text-gray-500">高速・日本語対応の音声認識エンジン</p>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  リアルタイム話者分離
                </label>
                <div className="bg-gray-50 p-3 rounded-lg">
                  <p className="text-sm text-gray-600">pyannote-seg INT8 / TitaNet small</p>
                  <p className="text-xs text-gray-500">話者を自動で識別・分離</p>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  停止後バッチ処理
                </label>
                <div className="bg-green-50 p-3 rounded-lg border border-green-200">
                  <p className="text-sm text-green-800 font-medium">OFF（推奨）</p>
                  <p className="text-xs text-green-600">必要時のみ faster-whisper small + CPU int8_float16 を使用</p>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  VAD（音声活動検出）
                </label>
                <div className="bg-gray-50 p-3 rounded-lg">
                  <p className="text-sm text-gray-600">Silero</p>
                  <div className="mt-2">
                    <label className="text-xs text-gray-500">応答重視 ←→ 誤検出低減</label>
                    <input 
                      type="range" 
                      min="0.3" 
                      max="0.8" 
                      step="0.1" 
                      defaultValue="0.55"
                      className="w-full mt-1"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {mode === 'advanced' && (
        <div className="space-y-6">
          {/* 詳細モード */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="text-lg font-semibold mb-4">詳細設定</h2>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <h3 className="font-medium text-gray-900 mb-3">プロバイダー設定</h3>
                <div className="space-y-2">
                  <label className="flex items-center gap-2">
                    <input type="radio" name="provider" value="cpu" defaultChecked />
                    <span className="text-sm">CPU（安定・推奨）</span>
                  </label>
                  <label className="flex items-center gap-2">
                    <input type="radio" name="provider" value="coreml" />
                    <span className="text-sm">CoreML（高速・Mac専用）</span>
                  </label>
                </div>
              </div>

              <div>
                <h3 className="font-medium text-gray-900 mb-3">クラスタリング</h3>
                <div className="space-y-2">
                  <label className="flex items-center gap-2">
                    <input type="radio" name="clustering" value="threshold" defaultChecked />
                    <span className="text-sm">しきい値ベース（リアルタイム）</span>
                  </label>
                  <label className="flex items-center gap-2">
                    <input type="radio" name="clustering" value="agglomerative" />
                    <span className="text-sm">凝集型（上級者向け）</span>
                  </label>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* モデル健診 */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold">モデル健診</h2>
          <button
            onClick={checkModels}
            disabled={isChecking}
            className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50"
          >
            {isChecking ? 'チェック中...' : '健診を実行'}
          </button>
        </div>

        {modelHealth && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 mb-4">
              <span className={`font-medium ${getStatusColor(modelHealth.ok)}`}>
                {getStatusIcon(modelHealth.ok)} {modelHealth.summary}
              </span>
            </div>

            <div className="space-y-3">
              {modelHealth.checks.map((check, index) => (
                <div 
                  key={index}
                  className={`p-4 rounded-lg border ${
                    check.ok 
                      ? 'bg-green-50 border-green-200' 
                      : 'bg-red-50 border-red-200'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <span className="text-lg">{getStatusIcon(check.ok)}</span>
                    <div className="flex-1">
                      <h3 className="font-medium text-gray-900">{check.name}</h3>
                      <p className="text-sm text-gray-600 font-mono">{check.path}</p>
                      
                      {check.issues.length > 0 && (
                        <div className="mt-2">
                          {check.issues.map((issue, i) => (
                            <p key={i} className="text-sm text-red-600">• {issue}</p>
                          ))}
                        </div>
                      )}

                      {check.ok && check.inputs && mode === 'advanced' && (
                        <details className="mt-2">
                          <summary className="text-sm text-gray-500 cursor-pointer">
                            技術詳細を表示
                          </summary>
                          <div className="mt-2 text-xs text-gray-600 space-y-1">
                            <div>
                              <strong>入力:</strong> {check.inputs.map(inp => `${inp.name} ${JSON.stringify(inp.shape)}`).join(', ')}
                            </div>
                            <div>
                              <strong>出力:</strong> {check.outputs?.map(out => `${out.name} ${JSON.stringify(out.shape)}`).join(', ')}
                            </div>
                          </div>
                        </details>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {!modelHealth && !isChecking && (
          <p className="text-gray-500 text-center py-4">
            「健診を実行」ボタンでモデルの状態をチェックできます
          </p>
        )}

        <div className="mt-6 bg-blue-50 rounded-lg p-4">
          <h3 className="font-medium text-blue-900 mb-2">モデル健診について</h3>
          <p className="text-sm text-blue-800">
            モデルの場所と形式をチェックしました。問題があれば、表示の手順どおり修正してください。
          </p>
        </div>
      </div>
    </div>
  )
}