export default function Help() {
  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">ヘルプ</h1>

      {/* 30秒チュートリアル */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-lg font-semibold mb-4">30秒チュートリアル</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <h3 className="font-medium text-gray-900 mb-3">📹 動画で見る（近日公開）</h3>
            <div className="bg-gray-100 rounded-lg p-8 text-center text-gray-500">
              BlackHole 配線→録音→ライブ字幕→保存
              <br />
              <span className="text-sm">(GIF動画)</span>
            </div>
          </div>
          <div>
            <h3 className="font-medium text-gray-900 mb-3">📝 手順</h3>
            <ol className="text-sm text-gray-700 space-y-2">
              <li>1. 入力ソースを選択（マイク/Meet/画面）</li>
              <li>2. 「開始」ボタンを押す</li>
              <li>3. 話すと数秒でライブ字幕が表示</li>
              <li>4. 「停止」ボタンで録音完了</li>
              <li>5. 会議詳細ページで結果を確認</li>
            </ol>
          </div>
        </div>
      </div>

      {/* よくある質問 */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-lg font-semibold mb-4">よくある質問</h2>
        <div className="space-y-4">
          <details id="forgot-password" className="border-b border-gray-200 pb-4">
            <summary className="font-medium text-gray-900 cursor-pointer hover:text-blue-600">
              🔐 パスワードを忘れました
            </summary>
            <div className="mt-3 text-sm text-gray-700 space-y-3">
              <p>管理者は以下の手順で任意のパスワードに再設定できます。</p>
              <ol className="list-decimal list-inside space-y-2">
                <li>バックエンドを停止し、プロジェクトルートで新しいハッシュを作成します。</li>
              </ol>
              <pre className="bg-gray-100 rounded-lg p-3 text-xs overflow-x-auto">
                {`python - <<'PY'
from passlib.context import CryptContext
pwd = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated="auto")
print(pwd.hash("NewSecurePassword123"))
PY`}
              </pre>
              <ol start={2} className="list-decimal list-inside space-y-2">
                <li>表示されたハッシュを控え、SQLiteに適用します。</li>
              </ol>
              <pre className="bg-gray-100 rounded-lg p-3 text-xs overflow-x-auto">
                {`sqlite3 backend/data/app.db "UPDATE users SET password_hash='<コピーしたハッシュ>' WHERE email='user@example.com';"`}
              </pre>
              <ol start={3} className="list-decimal list-inside space-y-2">
                <li>バックエンドを再起動し、新しいパスワードでログインします。</li>
              </ol>
              <p className="text-xs text-gray-500">※ 既存セッションは無効化されないため、必要に応じて backend/api/auth.py の /api/auth/logout を呼び出しセッションを削除してください。</p>
            </div>
          </details>

          <details className="border-b border-gray-200 pb-4">
            <summary className="font-medium text-gray-900 cursor-pointer hover:text-blue-600">
              🔧 音が出ない・録音できない
            </summary>
            <div className="mt-3 text-sm text-gray-700 space-y-3">
              <p><strong>マイク権限の問題:</strong></p>
              <ol className="list-decimal list-inside space-y-1 ml-4">
                <li><strong>Chrome:</strong> URL左側の🔒マークをクリック→マイクを「許可」に変更</li>
                <li><strong>Safari:</strong> メニュー「Safari」→「このWebサイトの設定」→マイクを「許可」</li>
                <li><strong>macOS:</strong> システム設定→プライバシーとセキュリティ→マイク→ブラウザにチェック</li>
                <li>ページを再読み込みしてもう一度お試しください</li>
              </ol>
              
              <p><strong>その他の確認事項:</strong></p>
              <ul className="list-disc list-inside space-y-1 ml-4">
                <li>マイクが物理的に接続されているか確認</li>
                <li>他のアプリ（Zoom、Teams等）でマイクが占有されていないか確認</li>
                <li>Bluetoothマイクの場合、ペアリング状態を確認</li>
                <li>マイクのミュートボタンが押されていないか確認</li>
              </ul>
              
              <p><strong>録音ページでの確認:</strong></p>
              <ul className="list-disc list-inside space-y-1 ml-4">
                <li>入力ソース下に表示される権限状態をチェック</li>
                <li>「❌ マイク拒否」の場合は上記の手順で権限を許可</li>
                <li>「⚠️ マイク権限不明」の場合は一度録音ボタンを押して権限を要求</li>
              </ul>
            </div>
          </details>

          <details className="border-b border-gray-200 pb-4">
            <summary className="font-medium text-gray-900 cursor-pointer hover:text-blue-600">
              📝 字幕が出ない・認識精度が悪い
            </summary>
            <div className="mt-3 text-sm text-gray-700 space-y-2">
              <p><strong>解決手順:</strong></p>
              <ol className="list-decimal list-inside space-y-1 ml-4">
                <li>設定→モデル健診で ASR モデルの状態を確認</li>
                <li>はっきりと話す（早口・小声だと認識が困難）</li>
                <li>背景ノイズを減らす</li>
                <li>VAD しきい値を調整（設定ページ）</li>
              </ol>
            </div>
          </details>

          <details className="border-b border-gray-200 pb-4">
            <summary className="font-medium text-gray-900 cursor-pointer hover:text-blue-600">
              👥 話者が混ざる・分離できない
            </summary>
            <div className="mt-3 text-sm text-gray-700 space-y-2">
              <p><strong>解決手順:</strong></p>
              <ol className="list-decimal list-inside space-y-1 ml-4">
                <li>設定→モデル健診で話者分離モデルの状態を確認</li>
                <li>各話者が2秒以上話すようにする</li>
                <li>話者間で十分な音声の違いがあることを確認</li>
                <li>同時発話を避ける</li>
              </ol>
            </div>
          </details>

          <details className="border-b border-gray-200 pb-4">
            <summary className="font-medium text-gray-900 cursor-pointer hover:text-blue-600">
              🎤 Google Meet の音声を取り込みたい
            </summary>
            <div className="mt-3 text-sm text-gray-700 space-y-2">
              <p><strong>BlackHole を使った方法:</strong></p>
              <ol className="list-decimal list-inside space-y-1 ml-4">
                <li>BlackHole をインストール</li>
                <li>macOS サウンド設定で出力を BlackHole に設定</li>
                <li>M4-Meet で入力ソースを「Google Meet（BlackHole）」に設定</li>
                <li>Google Meet の音声が録音されます</li>
              </ol>
              <p className="mt-2"><strong>画面キャプチャを使った方法:</strong></p>
              <ol className="list-decimal list-inside space-y-1 ml-4">
                <li>入力ソースを「タブの音声」に設定</li>
                <li>録音開始時にブラウザタブを選択</li>
                <li>「タブの音声を共有」にチェック</li>
              </ol>
            </div>
          </details>

          <details className="pb-4">
            <summary className="font-medium text-gray-900 cursor-pointer hover:text-blue-600">
              💾 データはどこに保存される？
            </summary>
            <div className="mt-3 text-sm text-gray-700">
              <p>すべてのデータはローカルに保存され、外部に送信されません:</p>
              <ul className="list-disc list-inside space-y-1 ml-4 mt-2">
                <li>音声ファイル: backend/artifacts/</li>
                <li>文字起こし: SQLite データベース</li>
                <li>設定: ローカルストレージ</li>
                <li>モデル: models/ ディレクトリ</li>
              </ul>
            </div>
          </details>

        </div>
      </div>

      {/* 技術情報 */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-lg font-semibold mb-4">技術情報</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <h3 className="font-medium text-gray-900 mb-3">使用技術</h3>
            <ul className="text-sm text-gray-700 space-y-1">
              <li>• <strong>音声認識:</strong> SenseVoice (sherpa-onnx)</li>
              <li>• <strong>話者分離:</strong> PyAnnote + TitaNet</li>
              <li>• <strong>VAD:</strong> Silero VAD</li>
              <li>• <strong>バッチ転記:</strong> faster-whisper</li>
              <li>• <strong>フロントエンド:</strong> React + TypeScript</li>
              <li>• <strong>バックエンド:</strong> FastAPI + Python</li>
            </ul>
          </div>
          <div>
            <h3 className="font-medium text-gray-900 mb-3">特徴</h3>
            <ul className="text-sm text-gray-700 space-y-1">
              <li>• 完全オフライン（インターネット不要）</li>
              <li>• リアルタイム文字起こし</li>
              <li>• 自動話者分離</li>
              <li>• Mac mini M4 最適化</li>
              <li>• プライバシー重視</li>
              <li>• 各種エクスポート形式対応</li>
            </ul>
          </div>
        </div>
      </div>

      {/* お問い合わせ */}
      <div className="bg-blue-50 rounded-xl p-6">
        <h2 className="text-lg font-semibold text-blue-900 mb-4">お問い合わせ</h2>
        <p className="text-sm text-blue-800 mb-3">
          問題が解決しない場合は、以下の情報とともにお問い合わせください:
        </p>
        <ul className="text-sm text-blue-700 space-y-1 ml-4">
          <li>• 設定→モデル健診の結果</li>
          <li>• 発生している具体的な問題</li>
          <li>• 使用環境（macOS バージョン、ブラウザなど）</li>
          <li>• エラーメッセージ（もしあれば）</li>
        </ul>
      </div>
    </div>
  )
}
