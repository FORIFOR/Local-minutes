M4-Meet: 完全ローカル会議管理Webアプリ (Mac mini M4)

本プロジェクトは完全ローカルで動作する会議管理Webアプリです。ASR/話者分離/翻訳/要約/TTS/全文検索/カレンダー/各種書き出しを提供します。外部インターネットは不要で、LLMは Ollama のローカルHTTP APIを利用します（必要に応じて llama.cpp へフォールバック可能）。

- Backend: FastAPI + Uvicorn + SQLite(FTS5)
- Frontend: Vite + React + Tailwind + Radix UI
- Realtime: 日本語ASR (sherpa-onnx), 準リアル話者分離、翻訳(CT2), ライブ要約(Ollama/Qwen2.5)
- Batch: Whisper Large-v3-Turbo(MPS) 再転記、最終要約/翻訳、各種エクスポート

前提

- Ollama: ローカルにインストール済みであること（モデル取得は手動）
- Node.js: 18以上（推奨）
- Python: 3.10以上（仮想環境を作成）
- macOS: Homebrew で `ffmpeg`/`sox`/`jq` が導入可能

セットアップと実行

1) 依存セットアップ（Ollamaは手動インストール）

```
# 1) リポジトリ直下で対話式セットアップ
npm run setup

# 2) Ollama（手動）を導入し、モデルを取得
brew install ollama            # または https://ollama.ai から入手
ollama pull qwen2.5:7b-instruct

# 3) 疎通確認（OKなら準備完了）
curl http://127.0.0.1:11434/v1/models
```

スクリプトが行うこと（npm run setup）
- Python仮想環境の作成と依存導入（選択式）
- Node依存（ルート+frontend）の導入（選択式）
- ASR/話者分離/翻訳(CT2)/TTSモデルのダウンロード（各項目ごとに選択）
- `.env` の自動生成（Ollama前提の変数を設定）

2) 開発起動/停止（Ctrl+Cで両方終了）

```
npm run dev   # Backend + Frontend を並列起動（ポートは自動調整）
# 起動後にブラウザが自動で開きます。停止は Ctrl+C。
```

従来の make ベースでも起動可能です:
```
make up   # 互換。内部で npm run dev を呼びます
```
停止:
```
Ctrl+C    # npm run dev 実行中
make down # 従来スクリプトで起動している場合
```

ログ確認:
```
make logs  # backend のアプリログを追尾
```

状態確認/ポート解放:
```
make status      # PIDファイルと 8000/5173 のLISTEN確認
make ports-kill  # 8000/5173 を掴んでいるプロセスを終了(要注意)
```

主要エンドポイント
- `GET /healthz` / `GET /healthz/ready`
- `POST /api/events` / `POST /api/events/{id}/start` / `POST /api/events/{id}/stop`
- `GET /api/events/{id}` / `GET /api/search?q=...`
 - 検索クエリは FTS5 構文。空文字や `*` の場合は最新イベントのプレビューを返します。

録音/文字起こしの流れ
- `Start` でWS接続し、ブラウザから送られた 16k/mono/PCM16 を `backend/artifacts/<event_id>/record.wav` に保存します。
- ライブASRは sherpa-onnx を使用。CoreMLが使えない/初期化失敗時はCPUにフォールバックします。
- `Stop` を押すとバッチ再転記(Whisper Large-v3-Turbo/MPS)が動き、`record.wav` からセグメントをDBへ取り込みます。
- LLM/翻訳/TTSは導入済みの場合のみ動作します(未導入でも録音→バッチ転記は可能)。

注意(ONNXRuntimeの重複警告)
- `sherpa-onnx` と `onnxruntime` を併用すると macOS で `CoreMLExecution is implemented in both ...` の警告が出る場合があります。現実装はCoreMLを使わずCPUを優先することで回避しています(性能より安定重視)。
- `POST /api/events/{id}/translate`
- `GET /download.(srt|vtt|rttm|ics)?id=...`
- `WS /ws/stream?event_id&token`

.env 例
`.env.example` を参照してください。

ローカルLLM(要約)の設定例
- llama.cpp を使う場合（フォールバック/任意）:
  - `M4_LLM_PROVIDER=` (未設定でOK)
  - `M4_LLM_BIN=llama` (Homebrewのバイナリ名に合わせる。従来の `llama-cli` でも可)
  - `M4_LLM_MODEL=/path/to/model.gguf`
- Ollama を使う場合（OpenAI互換API 推奨・既定）:
  - 事前に Ollama を起動し、`qwen2.5:7b-instruct` を取得
    - 動作確認: `ollama run qwen2.5:7b-instruct "こんにちは"`
    - 128k前提で使う場合は派生を作成（任意）
      - 例: 
        - `ollama create qwen25-7b-sum128k -f - << 'EOF'`
        - `FROM qwen2.5:7b-instruct`
        - `PARAMETER num_ctx 131072`
        - `PARAMETER temperature 0.3`
        - `EOF`
  - `.env` に以下を設定
    - `M4_LLM_PROVIDER=ollama`
    - `M4_OLLAMA_BASE=http://127.0.0.1:11434`
    - `M4_OLLAMA_MODEL=qwen2.5:7b-instruct` （派生を使う場合はそのモデル名）
    - `M4_OLLAMA_TEMPERATURE=0.3`
    - `M4_OLLAMA_MAX_TOKENS=768`
    - `M4_OLLAMA_TIMEOUT=180`
  - 健診: `GET /api/health/models` の `Ollama API` が ok であることを確認
  - テスト: `curl http://127.0.0.1:11434/v1/models`

自己テスト
```
make test
```
- モデル未導入時は `ready=false` でフェイルファースト
- モデル導入済みなら WS/再転記/検索/TTS まで通ります

注意
- スタブ/モックは不使用。音声やモデルはローカルに保存します。
- LLMはOllamaのローカルHTTP APIを利用します（外部インターネット不要）。

クリーンアップ（リポジトリ）
- ログやビルド成果物は追跡しません:
  - `backend/data/*.log` … 実行時に生成されます
  - `frontend/dist/` … `vite build` で生成されます
  必要に応じて再生成してください。

トラブルシュート（Ollama）
- `ollama run` は `-p` フラグを使いません。例: `ollama run qwen2.5:7b-instruct "こんにちは"`
- `curl http://127.0.0.1:11434/v1/models` が通らない場合は `ollama serve` の起動やファイアウォールを確認
- モデル名のミスが多いです: `qwen2.5:7b-instruct` と `qwen25-7b-sum128k`（派生）の混同に注意
