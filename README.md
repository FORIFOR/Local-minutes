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

## 開発モードでの起動

Backend と Frontend を同時起動(Ctrl+C で両方終了):

```bash
npm run dev   # ポートは自動調整され、ブラウザが自動で開きます
```

従来の make ベースでも起動可能:
```bash
make up   # 互換。内部で npm run dev を呼びます
```

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
