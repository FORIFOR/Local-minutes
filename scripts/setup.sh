#!/usr/bin/env bash
set -euo pipefail

echo "[setup] 対話式セットアップ (Ollama手動) を開始します"

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

if [ -f .env ]; then
  echo "[setup] 既存の .env が見つかりました。上書きせずに継続します。"
fi

read -r -p "Homebrew/基本依存 (ffmpeg/sox/jq) を導入しますか? (y/N) " yn
if [[ ${yn:-N} == y || ${yn:-N} == Y ]]; then
  /bin/bash -lc 'brew update && brew install ffmpeg sox jq'
fi

read -r -p "Python venv と Python依存を導入しますか? (y/N) " yn
if [[ ${yn:-N} == y || ${yn:-N} == Y ]]; then
  # 既存の.venvが移動により壊れている場合は再作成
  if [ -d .venv ] && [ ! -x .venv/bin/python3 ]; then
    echo "[setup] 既存の .venv が壊れています。再作成します。"
    rm -rf .venv
  fi
  /bin/bash -lc 'python3 -m venv .venv && . .venv/bin/activate && python3 -m pip install -U pip wheel && python3 -m pip install -r backend/requirements.txt'
fi

read -r -p "Node.js 依存 (root + frontend) を導入しますか? (y/N) " yn
if [[ ${yn:-N} == y || ${yn:-N} == Y ]]; then
  echo "[setup] root の npm 依存をインストール"
  (cd "$ROOT_DIR" && npm install)
  echo "[setup] frontend の npm 依存をインストール"
  (cd "$ROOT_DIR/frontend" && npm install)
fi

DEFAULT_MODELS_DIR="$HOME/m4-meet-models"
read -r -p "モデル格納ディレクトリ [${DEFAULT_MODELS_DIR}] > " MODELS_DIR
MODELS_DIR=${MODELS_DIR:-$DEFAULT_MODELS_DIR}
mkdir -p "$MODELS_DIR"

echo "[setup] モデルのダウンロード(同意したもののみ)"

read -r -p "ASR (sherpa-onnx 日本語) をダウンロードしますか? (y/N) " yn
if [[ ${yn:-N} == y || ${yn:-N} == Y ]]; then
  echo "URL: https://github.com/k2-fsa/sherpa-onnx/releases/.../sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01.tar.bz2"
  mkdir -p "$MODELS_DIR/sherpa_jp"
  cd "$MODELS_DIR/sherpa_jp"
  curl -L -o asr.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01.tar.bz2
  tar xf asr.tar.bz2 && rm asr.tar.bz2
  cd "$ROOT_DIR"
fi

read -r -p "話者分離(セグメンテーション) をダウンロードしますか? (y/N) " yn
if [[ ${yn:-N} == y || ${yn:-N} == Y ]]; then
  mkdir -p "$MODELS_DIR/diar"
  cd "$MODELS_DIR/diar"
  echo "URL(seg): https://github.com/k2-fsa/sherpa-onnx/.../sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
  curl -L -o seg.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2
  tar xf seg.tar.bz2 && rm seg.tar.bz2
  cd "$ROOT_DIR"
fi

read -r -p "話者分離(埋め込み: TitaNet) をダウンロードしますか? (y/N) " yn
if [[ ${yn:-N} == y || ${yn:-N} == Y ]]; then
  mkdir -p "$MODELS_DIR/diar"
  cd "$MODELS_DIR/diar"
  echo "URL(emb): https://github.com/k2-fsa/sherpa-onnx/.../nemo_en_titanet_small.onnx"
  curl -L -o nemo_en_titanet_small.onnx https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/nemo_en_titanet_small.onnx
  cd "$ROOT_DIR"
fi

# 要約LLMはOllama(Qwen2.5)を前提とし、インストールは手動です（下のメッセージ参照）

read -r -p "翻訳 CT2(M2M100 418M) をダウンロードしますか? (y/N) " yn
if [[ ${yn:-N} == y || ${yn:-N} == Y ]]; then
  mkdir -p "$MODELS_DIR/ct2_m2m100_418m"
  cd "$MODELS_DIR/ct2_m2m100_418m"
  echo "URL(CT2): https://huggingface.co/.../model.tar.gz"
  curl -L -o model.tar.gz https://huggingface.co/michaelfeil/ct2fast-m2m100_418M/resolve/main/model.tar.gz
  tar xf model.tar.gz && rm model.tar.gz
  cd "$ROOT_DIR"
fi

read -r -p "TTS Piper 日本語音声をダウンロードしますか? (y/N) " yn
if [[ ${yn:-N} == y || ${yn:-N} == Y ]]; then
  mkdir -p "$MODELS_DIR/tts/piper"
  cd "$MODELS_DIR/tts/piper"
  echo "URL(TTS onnx/json)"
  curl -L -o ja_JP-lessac-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/ja/ja_JP/lessac/ja_JP-lessac-medium.onnx
  curl -L -o ja_JP-lessac-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/ja/ja_JP/lessac/ja_JP-lessac-medium.onnx.json
  cd "$ROOT_DIR"
fi

echo "[setup] .env を生成します"
cat > .env <<EOF
M4_MODELS_DIR=${MODELS_DIR}
M4_ASR_DIR=${MODELS_DIR}/sherpa_jp
M4_DIAR_DIR=${MODELS_DIR}/diar
# 任意(導入時のみ有効): 翻訳/CT2, TTS
M4_CT2_DIR=${MODELS_DIR}/ct2_m2m100_418m
M4_TTS_VOICE=${MODELS_DIR}/tts/piper/ja_JP-lessac-medium.onnx

# LLM: 既定は Ollama(Qwen2.5)
M4_LLM_PROVIDER=ollama
M4_OLLAMA_BASE=http://127.0.0.1:11434
M4_OLLAMA_MODEL=qwen2.5:7b-instruct
M4_OLLAMA_TEMPERATURE=0.3
M4_OLLAMA_MAX_TOKENS=768
M4_OLLAMA_TIMEOUT=180

# ポート/ログ
PORT_BACKEND=8000
PORT_FRONTEND=5173
LOG_DIR=backend/data

# ランタイム挙動
M4_ASR_KIND=sense-voice-offline
M4_ASR_LIVE=1
M4_BATCH_WHISPER=off
M4_BATCH_TRANSLATE=off
M4_BATCH_SUMMARY=off
EOF

mkdir -p backend/data backend/artifacts data models

cat <<'TIP'
[setup] 完了。

次の手順（手動 / 1回だけ）:
  1) Ollama をインストール:   https://ollama.ai
  2) モデル取得:               ollama pull qwen2.5:7b-instruct
     (任意: 128k派生)         ollama create qwen25-7b-sum128k -f - << EOF
                               FROM qwen2.5:7b-instruct
                               PARAMETER num_ctx 131072
                               PARAMETER temperature 0.3
                               EOF
  3) 疎通確認:                 curl http://127.0.0.1:11434/v1/models

開発起動:
  npm run dev   # Backend + Frontend 同時起動（ポート自動調整）
TIP
