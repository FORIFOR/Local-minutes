# セットアップガイド - 他のMac環境へのデプロイ

このドキュメントは、M4-Meetを新しいMac環境にセットアップする手順を説明します。

## 概要

M4-Meetは以下の理由でGitリポジトリにモデルファイルを含めていません:
- モデルファイルの合計サイズが約2GB
- GitHubのファイルサイズ制限(100MB/ファイル)
- 各環境でモデルをダウンロードすることで、リポジトリサイズを小さく保つ

## 前提条件

新しいMac環境に以下がインストールされている必要があります:

1. **Homebrew** - macOSのパッケージマネージャー
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

2. **Node.js** (v18以上)
   ```bash
   brew install node
   node --version  # v18以上を確認
   ```

3. **Python 3** (v3.10以上)
   ```bash
   python3 --version  # 通常はmacOSにプリインストール済み
   ```

4. **Git**
   ```bash
   git --version  # 通常はmacOSにプリインストール済み
   ```

## ステップバイステップセットアップ

### ステップ 1: リポジトリのクローン

```bash
# 任意の作業ディレクトリに移動
cd ~/workspace  # または任意のディレクトリ

# リポジトリをクローン
git clone https://github.com/FORIFOR/Local-minutes.git
cd Local-minutes
```

### ステップ 2: 自動セットアップスクリプトの実行

対話式セットアップスクリプトを実行します。このスクリプトは必要な依存関係とモデルを対話的にダウンロードします。

```bash
npm run setup
```

セットアップスクリプトは以下の項目について確認します(各項目で y/N を選択):

1. **Homebrew/基本依存 (ffmpeg/sox/jq)** - 音声処理に必要
2. **Python venv と Python依存** - Pythonバックエンドに必要
3. **Node.js依存** - フロントエンドとビルドツールに必要
4. **モデルのダウンロード**:
   - ASR (音声認識) モデル - SenseVoice オフライン日本語対応
   - 話者分離(セグメンテーション) - 話者識別に必要
   - 話者分離(埋め込み: TitaNet) - 話者識別に必要
   - 翻訳 CT2(M2M100 418M) - 多言語翻訳に必要(オプション)
   - TTS Piper 日本語音声 - 音声合成に必要(オプション)

**推奨**: 初回セットアップでは全て `y` を選択することをお勧めします。

モデルは `~/m4-meet-models` にダウンロードされます(カスタマイズ可能)。

### ステップ 3: Ollamaのインストール

Ollama は要約機能に使用するLLMサーバーです。

```bash
# Homebrewでインストール
brew install ollama

# または公式サイトからダウンロード
# https://ollama.ai
```

### ステップ 4: Ollamaモデルのダウンロード

```bash
# Qwen2.5モデルをダウンロード(約5GB)
ollama pull qwen2.5:7b-instruct

# 動作確認
ollama run qwen2.5:7b-instruct "こんにちは"
# 正常に応答が返れば成功
```

**(オプション) 128kコンテキストの派生モデルを作成**

長い会議の要約に128kコンテキストが必要な場合:

```bash
ollama create qwen25-7b-sum128k -f - << 'EOF'
FROM qwen2.5:7b-instruct
PARAMETER num_ctx 131072
PARAMETER temperature 0.3
EOF
```

派生モデルを使用する場合は `.env` の `M4_OLLAMA_MODEL` を `qwen25-7b-sum128k` に変更してください。

### ステップ 5: 環境設定の確認

セットアップスクリプトは自動で `.env` ファイルを生成します。確認してください:

```bash
cat .env
```

主要な設定項目:
- `M4_MODELS_DIR`: モデル格納ディレクトリ
- `M4_LLM_PROVIDER`: LLMプロバイダー(ollama推奨)
- `M4_OLLAMA_MODEL`: 使用するOllamaモデル名
- `PORT_BACKEND`: バックエンドポート(デフォルト: 8000)
- `PORT_FRONTEND`: フロントエンドポート(デフォルト: 5173)

カスタマイズが必要な場合は `.env` を編集してください。

### ステップ 6: 疎通確認

```bash
# Ollama APIが正常に動作しているか確認
curl http://127.0.0.1:11434/v1/models
```

正常に応答があれば準備完了です。

### ステップ 7: アプリケーションの起動

```bash
# 開発モードで起動
npm run dev
```

以下が自動的に実行されます:
- バックエンドサーバーが起動(ポート8000)
- フロントエンドサーバーが起動(ポート5173)
- デフォルトブラウザが自動で開きます

停止するには `Ctrl+C` を押してください。

## ディレクトリ構造

セットアップ完了後のディレクトリ構造:

```
Local-minutes/
├── .env                    # 環境設定(自動生成)
├── .env.example           # 環境設定のサンプル
├── .gitignore             # Git除外設定
├── backend/               # Pythonバックエンド
│   ├── requirements.txt   # Python依存関係
│   ├── main.py           # エントリーポイント
│   └── artifacts/        # 録音データ(自動生成)
├── frontend/              # Reactフロントエンド
│   ├── package.json      # Node.js依存関係
│   └── src/              # ソースコード
├── models/               # モデル格納(Git除外、セットアップで作成)
├── scripts/              # セットアップ・起動スクリプト
│   └── setup.sh          # 自動セットアップ
├── package.json          # ルートパッケージ設定
├── Makefile             # makeコマンド定義
└── README.md            # プロジェクト概要
```

**重要**: `models/` ディレクトリはGitで追跡されません。

## トラブルシューティング

### Python仮想環境のエラー

```bash
# 仮想環境を再作成
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### Node.jsモジュールのエラー

```bash
# node_modulesを再インストール
rm -rf node_modules frontend/node_modules
npm install
cd frontend && npm install
```

### モデルのダウンロードエラー

セットアップスクリプトでモデルのダウンロードに失敗した場合、手動でダウンロードできます:

```bash
# モデル格納ディレクトリを作成
mkdir -p ~/m4-meet-models

# ASRモデル(日本語: SenseVoice offline)
mkdir -p ~/m4-meet-models/sensevoice
cd ~/m4-meet-models/sensevoice
curl -L -o model.int8.onnx https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/model.int8.onnx
curl -L -o model.onnx https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/model.onnx
curl -L -o tokens.txt https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/tokens.txt

# 話者分離(セグメンテーション)
mkdir -p ~/m4-meet-models/diar
cd ~/m4-meet-models/diar
curl -L -o seg.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2
tar xf seg.tar.bz2 && rm seg.tar.bz2

# 話者分離(埋め込み)
curl -L -o nemo_en_titanet_small.onnx https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/nemo_en_titanet_small.onnx
```

### Ollamaの接続エラー

```bash
# Ollamaが起動しているか確認
ollama list

# Ollamaを再起動
brew services restart ollama

# または手動起動
ollama serve
```

### ポート競合エラー

```bash
# 使用中のポートを確認
lsof -i :8000
lsof -i :5173

# プロセスを終了
make ports-kill  # 注意: 8000と5173のプロセスを強制終了
```

## ディスク容量の目安

- リポジトリ本体: 約100MB
- Python依存関係(.venv): 約1.5GB
- Node.js依存関係(node_modules): 約200MB
- モデルファイル: 約2GB
- Ollamaモデル: 約5GB

**合計**: 約9GB程度の空き容量が必要です。

## 次のステップ

セットアップが完了したら:
1. `npm run dev` でアプリケーションを起動
2. ブラウザで `http://localhost:5173` を開く
3. 新しい会議イベントを作成して録音を開始
4. README.mdで機能の詳細を確認

## サポート

問題が発生した場合:
1. このドキュメントのトラブルシューティングを確認
2. README.mdの「トラブルシュート」セクションを確認
3. GitHubのIssuesで報告
