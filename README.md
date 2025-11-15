# M4-Meet: 完全ローカル会議管理Webアプリ

本プロジェクトは完全ローカルで動作する会議管理Webアプリです。ASR/話者分離/翻訳/要約/TTS/全文検索/カレンダー/各種書き出しを提供します。外部インターネットは不要で、LLMは Ollama のローカルHTTP APIを利用します(必要に応じて llama.cpp へフォールバック可能)。

## 特徴

- **Backend**: FastAPI + Uvicorn + SQLite(FTS5)
- **Frontend**: Vite + React + Tailwind + Radix UI
- **Realtime**: 日本語ASR (sherpa-onnx), 準リアル話者分離、翻訳(CT2), ライブ要約(Ollama/Qwen2.5)
- **Batch**: Whisper Large-v3-Turbo(MPS) 再転記、最終要約/翻訳、各種エクスポート

## 前提条件

- **Ollama**: ローカルにインストール済みであること(モデル取得は手動)
- **Node.js**: 18以上(推奨)
- **Python**: 3.10以上(仮想環境を作成)
- **macOS**: Homebrew で `ffmpeg`/`sox`/`jq` が導入可能

## 初回セットアップ手順

### 1. リポジトリのクローン

```bash
git clone https://github.com/FORIFOR/Local-minutes.git
cd Local-minutes
```

### 2. 対話式セットアップの実行

以下のコマンドで、必要な依存関係とモデルを対話的にダウンロードできます:

```bash
npm run setup
```

このスクリプトは以下を実行します:
- Python仮想環境の作成と依存関係のインストール(選択式)
- Node.js依存関係のインストール(ルート + frontend)(選択式)
- ASR/話者分離/翻訳/TTSモデルのダウンロード(各項目ごとに選択)
- `.env` ファイルの自動生成

**重要**: モデルファイルはGitリポジトリに含まれていません。初回セットアップ時に自動でダウンロードされます(合計約2GB程度)。

### 3. Ollamaのインストールとモデル取得(手動)

```bash
# Ollamaのインストール
brew install ollama            # または https://ollama.ai から入手

# モデルの取得
ollama pull qwen2.5:7b-instruct

# (オプション) 128kコンテキストの派生モデルを作成
ollama create qwen25-7b-sum128k -f - << 'EOF'
FROM qwen2.5:7b-instruct
PARAMETER num_ctx 131072
PARAMETER temperature 0.3
EOF
```

### 4. 疎通確認

```bash
# Ollama APIが正常に動作しているか確認
curl http://127.0.0.1:11434/v1/models
```

正常に応答があれば準備完了です。

### 5. TypeScript 型チェック (任意)

フロントエンドの型定義が正しく解決されているか確認するには、以下を実行します:

```bash
npm run typecheck
```

エラーが出る場合は依存パッケージや生成ファイルが不足している可能性があるので、`npm run setup` を再実行して `.env` とモデルのパスを確認してください。

## 開発モードでの起動

Backend と Frontend を同時起動(Ctrl+C で両方終了):

```bash
npm run dev   # ポートは自動調整され、ブラウザが自動で開きます
```

- バックエンドは `http://127.0.0.1:8000` で待ち受けます。開発サーバーは自動的にプロキシするため、フロントエンド側で追加設定を行う必要はありません。
- `npm run dev` でフロントエンドが自動で `/` を開きますが、未ログイン時は `/auth/login` に遷移して認証してください。
- ホスト名を固定したい場合は `DEV_BACKEND_HOST` / `DEV_FRONTEND_HOST` / `DEV_FRONTEND_PORT` を環境変数で指定できます（例: `DEV_FRONTEND_HOST=0.0.0.0 npm run dev`）。

### 同一LAN内の別端末からアクセスする

`npm run dev` 実行時にバックエンド/フロントエンドの開発サーバーを `0.0.0.0` バインドで起動するよう修正済みです。以下を参照してください。

1. `npm run dev` を実行すると、コンソールに `UI: http://localhost:5173` とあわせて `UI (LAN): http://<ローカルIP>:5173` が表示されます。別端末はこの URL でアクセスできます。
2. macOS のファイアウォールを有効にしている場合は、Node.js / Python（uvicorn）への受信を許可してください。
3. 認証や SSE はすべて同一オリジン (`http://<ローカルIP>:5173`) 経由でプロキシされるため、追加の設定は不要です。
4. バックエンドの API を直接叩く必要がある場合は `http://<ローカルIP>:8000` を利用できます。

> インターネット経由で公開する場合は、Cloudflare Tunnel や Tailscale などの安全なトンネルの利用を推奨します。直接ポート開放を行う際は TLS/認証の保護を必ず追加してください。

従来の make ベースでも起動可能:
```bash
make up   # 互換。内部で npm run dev を呼びます
```

## 本番運用 (UIのみHTTPS公開)

1. **バックエンドとUIをローカルで起動**

   ```bash
   # バックエンドはローカルホストで待ち受け
   PORT_BACKEND=8000 DEV_BACKEND_HOST=127.0.0.1 npm run start

   # フロントエンドをビルド
   npm run build

   # プロキシ付きUIサーバーを起動（バックエンドを同一ホストのみに閉じたまま）
   BACKEND_BASE=http://127.0.0.1:8000 FRONTEND_HOST=127.0.0.1 FRONTEND_PORT=3000 npm run serve:frontend
   ```

   `proxy/server.js` が `/api` や SSE (`/api/events/:id/summary/stream`) を内部で FastAPI に転送するため、ブラウザは UI サーバーだけを見れば OK です。

2. **TLS終端のリバースプロキシを配置**

   - `deploy/Caddyfile` または `deploy/nginx.conf` のサンプルを使用し、`ui.example.com` などのドメインで HTTPS を終端します。
   - このプロキシのみを外部公開し、ポート 3000/8000 はファイアウォールで閉じます。

3. **環境変数まとめ**

   | 変数 | 役割 |
   | --- | --- |
   | `BACKEND_BASE` | UIサーバーから参照する FastAPI の URL（既定 `http://127.0.0.1:8000`） |
   | `FRONTEND_HOST` / `FRONTEND_PORT` | UIサーバーの待受ホスト/ポート（既定 `0.0.0.0:3000`） |
   | `M4_BATCH_SUMMARY` `M4_LLM_PROVIDER` | 要約実行の有無と LLM 接続先 |

4. **SSE/認証の確認**

   - ブラウザ → `https://ui.example.com` で要約生成を行い、ネットワークタブで `/api/events/<id>/summary/stream` が 200 / `text/event-stream` になっていることを確認します。
   - FastAPI に直接アクセスできないこと（`curl http://<public-ip>:8000` が失敗すること）を確認します。

## Cloudflare Pages + Render でのクラウド公開

ローカルで録音／要約を行い、結果だけクラウドに送る構成を採る場合は以下の手順で
フロントエンドを Cloudflare Pages、バックエンドを Render に配置します。

### 1. Vite の環境変数を分離

`frontend/.env.development` と `frontend/.env.production` を追加し、

```
# frontend/.env.development
VITE_API_BASE=http://localhost:8001
VITE_WS_BASE=ws://localhost:8001
VITE_ENABLE_GOOGLE_LOGIN=true
VITE_ENABLE_GOOGLE_SYNC=true

# frontend/.env.production
VITE_API_BASE=https://m4-meet-backend.onrender.com
VITE_WS_BASE=wss://m4-meet-backend.onrender.com
VITE_ENABLE_GOOGLE_LOGIN=true
VITE_ENABLE_GOOGLE_SYNC=true
```

というように API/WS の接続先を切り替えます。`frontend/src/lib/config.ts`
では `import.meta.env.VITE_API_BASE` 等を参照しています。

### 2. Cloudflare Pages でビルド

1. Cloudflare ダッシュボード → *Workers & Pages* → **Create application** → Pages
2. GitHub の本リポジトリを接続
3. Build 設定
   - **Root directory**: `frontend`
   - **Build command**: `npm run build`
   - **Build output directory**: `dist`
   - **Framework preset**: Vite
4. Environment variables に `VITE_API_BASE=https://m4-meet-backend.onrender.com`
   (必要であれば `VITE_ENABLE_GOOGLE_LOGIN=true` など) を登録
5. Deploy を実行し、`https://<project>.pages.dev` が生成されることを確認

### 3. Render 側の CORS を更新

Render で稼働している FastAPI（`backend/main_cloud.py`）の CORS 設定に
Cloudflare Pages の URL (`https://<project>.pages.dev`) を追加します。
これで Pages → Render 間の `fetch` とクッキー認証が許可されます。

### 4. 動作確認

- Cloudflare Pages 上の UI で Google ログインや会議一覧が機能するか
- Network タブで API リクエストが `https://m4-meet-backend.onrender.com` に飛んでいるか
- Render ログに 200 OK が記録されているか

必要に応じて Pages に Custom Domain を割り当て、Google OAuth の
Javascript origin / Redirect URI に追加してください。

## ユーザ管理

- 初回アクセス時は WebUI の `/auth/register` からユーザを作成してください。
- 既存ユーザは `/auth/login` からサインインできます。
- セッションはブラウザのクッキーで管理され、ログアウトはヘッダーの「ログアウト」から実行できます。

## 停止とログ確認

```bash
# 停止
Ctrl+C    # npm run dev 実行中
make down # 従来スクリプトで起動している場合

# ログ確認
make logs  # backend のアプリログを追尾

# 状態確認/ポート解放
make status      # PIDファイルと 8000/5173 のLISTEN確認
make ports-kill  # 8000/5173 を掴んでいるプロセスを終了(要注意)
```

## 主要エンドポイント

- `GET /healthz` / `GET /healthz/ready`
- `POST /api/events` / `POST /api/events/{id}/start` / `POST /api/events/{id}/stop`
- `GET /api/events/{id}` / `GET /api/search?q=...`
  - 検索クエリは FTS5 構文。空文字や `*` の場合は最新イベントのプレビューを返します。
- `POST /api/events/{id}/translate`
- `GET /download.(srt|vtt|rttm|ics)?id=...`
- `WS /ws/stream?event_id&token`

## 録音/文字起こしの流れ

- `Start` でWS接続し、ブラウザから送られた 16k/mono/PCM16 を `backend/artifacts/<event_id>/record.wav` に保存します。
- ライブASRは sherpa-onnx を使用。CoreMLが使えない/初期化失敗時はCPUにフォールバックします。
- `Stop` を押すとバッチ再転記(Whisper Large-v3-Turbo/MPS)が動き、`record.wav` からセグメントをDBへ取り込みます。
- LLM/翻訳/TTSは導入済みの場合のみ動作します(未導入でも録音→バッチ転記は可能)。

## 環境設定(.env)

`.env.example` を参照してください。主要な設定項目:
- `M4_MODELS_DIR` / `M4_ASR_DIR` / `M4_ASR_MODEL`: モデル格納先と SenseVoice の ONNX/TOKEN パス
- `M4_VAD_THRESHOLD`: Silero VAD の感度（0.0 に近いほど敏感、既定 0.28）
- `M4_VAD_RMS_FALLBACK`: 無音判定時に擬似セグメントを生成する RMS 閾値（既定 0.003）
- `M4_LLM_PROVIDER` 〜 `M4_OLLAMA_*`: 要約用 LLM の接続設定
- `M4_BATCH_WHISPER`: `on` にすると停止後に Whisper バッチ再転記（既定 on）
- `M4_BATCH_TRANSLATE`: 翻訳を有効化する場合は `on`（翻訳モデル要設置）
- `M4_BATCH_SUMMARY`: 要約を自動生成する場合は `on`（Ollama などの LLM 必須）
- `PORT_BACKEND` / `PORT_FRONTEND`: サーバーのポート番号

### ローカルLLM(要約)の設定例

**推奨: Ollama を使う場合(OpenAI互換API)**

事前に Ollama を起動し、`qwen2.5:7b-instruct` を取得:
```bash
ollama run qwen2.5:7b-instruct "こんにちは"  # 動作確認

# 128k前提で使う場合は派生を作成(任意)
ollama create qwen25-7b-sum128k -f - << 'EOF'
FROM qwen2.5:7b-instruct
PARAMETER num_ctx 131072
PARAMETER temperature 0.3
EOF
```

`.env` に以下を設定:
```
M4_LLM_PROVIDER=ollama
M4_OLLAMA_BASE=http://127.0.0.1:11434
M4_OLLAMA_MODEL=qwen2.5:7b-instruct
M4_OLLAMA_TEMPERATURE=0.3
M4_OLLAMA_MAX_TOKENS=768
M4_OLLAMA_TIMEOUT=180
```

健診: `GET /api/health/models` の `Ollama API` が ok であることを確認
テスト: `curl http://127.0.0.1:11434/v1/models`

**代替: llama.cpp を使う場合(フォールバック/任意)**

```
M4_LLM_PROVIDER=  # 未設定でOK
M4_LLM_BIN=llama  # Homebrewのバイナリ名に合わせる
M4_LLM_MODEL=/path/to/model.gguf
```

## テスト

```bash
make test
```

- モデル未導入時は `ready=false` でフェイルファースト
- モデル導入済みなら WS/再転記/検索/TTS まで通ります

## 注意事項

### ONNXRuntimeの重複警告
`sherpa-onnx` と `onnxruntime` を併用すると macOS で `CoreMLExecution is implemented in both ...` の警告が出る場合があります。現実装はCoreMLを使わずCPUを優先することで回避しています(性能より安定重視)。

### モデルファイルについて
スタブ/モックは不使用。音声やモデルはローカルに保存します。モデルファイルは `.gitignore` で除外されているため、Gitリポジトリには含まれません。各マシンで `npm run setup` を実行して必要なモデルをダウンロードしてください。

### クリーンアップ(リポジトリ)
ログやビルド成果物は追跡しません:
- `backend/data/*.log` … 実行時に生成されます
- `frontend/dist/` … `vite build` で生成されます
- `models/` … セットアップ時にダウンロードされます

必要に応じて再生成してください。

## トラブルシュート

### Ollama関連
- `ollama run` は `-p` フラグを使いません。例: `ollama run qwen2.5:7b-instruct "こんにちは"`
- `curl http://127.0.0.1:11434/v1/models` が通らない場合は `ollama serve` の起動やファイアウォールを確認
- モデル名のミスが多いです: `qwen2.5:7b-instruct` と `qwen25-7b-sum128k`(派生)の混同に注意

### ポート競合
- Backend: 8000, Frontend: 5173 がデフォルト
- `.env` の `PORT_BACKEND` と `PORT_FRONTEND` で変更可能
- `make ports-kill` で強制的にポートを解放できます(注意して使用)

## 他のMac環境へのセットアップ

1. このリポジトリをクローン
2. `npm run setup` を実行して対話的にセットアップ
3. Ollama を手動でインストールし、モデルを取得
4. `npm run dev` で起動

全ての設定は `.env` ファイルに保存されます。環境変数は `.env.example` を参照してカスタマイズできます。
