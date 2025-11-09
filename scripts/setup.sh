#!/usr/bin/env bash
set -euo pipefail

echo "[setup] 対話式セットアップ (Ollama手動) を開始します"

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

PYTHON_MIN_VERSION_MAJOR=3
PYTHON_MIN_VERSION_MINOR=10

python_supports_required_version() {
  local cmd="$1"
  "$cmd" -c "import sys; sys.exit(0 if sys.version_info[:2] >= ($PYTHON_MIN_VERSION_MAJOR, $PYTHON_MIN_VERSION_MINOR) else 1)" >/dev/null 2>&1
}

python_version_string() {
  local cmd="$1"
  "$cmd" -c 'import platform; print(platform.python_version())'
}

python_from_venv() {
  local venv_dir="$1"
  if [ -x "$venv_dir/bin/python3" ]; then
    echo "$venv_dir/bin/python3"
  elif [ -x "$venv_dir/bin/python" ]; then
    echo "$venv_dir/bin/python"
  else
    echo ""
  fi
}

choose_python_bin() {
  local candidates=()
  if [ -n "${M4_PYTHON_BIN:-}" ]; then
    candidates+=("$M4_PYTHON_BIN")
  fi
  candidates+=(python3.12 python3.11 python3.10 python3)
  for candidate in "${candidates[@]}"; do
    if command -v "$candidate" >/dev/null 2>&1; then
      local resolved
      resolved=$(command -v "$candidate")
      if python_supports_required_version "$resolved"; then
        echo "$resolved"
        return 0
      fi
    fi
  done
  return 1
}

if [ -f .env ]; then
  echo "[setup] 既存の .env が見つかりました。上書きせずに継続します。"
fi

read -r -p "Homebrew/基本依存 (ffmpeg/sox/jq) を導入しますか? (y/N) " yn
if [[ ${yn:-N} == y || ${yn:-N} == Y ]]; then
  /bin/bash -lc 'brew update && brew install ffmpeg sox jq'
fi

read -r -p "Python venv と Python依存を導入しますか? (y/N) " yn
if [[ ${yn:-N} == y || ${yn:-N} == Y ]]; then
  VENV_DIR=${M4_VENV_DIR:-.venv}
  ACTIVE_PYTHON=""

  if [ -n "${VIRTUAL_ENV:-}" ]; then
    ACTIVE_PYTHON=$(python_from_venv "$VIRTUAL_ENV")
    if [ -z "$ACTIVE_PYTHON" ]; then
      ACTIVE_PYTHON="python"
    fi

    if ! python_supports_required_version "$ACTIVE_PYTHON"; then
      version=$(python_version_string "$ACTIVE_PYTHON")
      echo "[setup] 現在の仮想環境 ($VIRTUAL_ENV) の Python は ${version} です。Python ${PYTHON_MIN_VERSION_MAJOR}.${PYTHON_MIN_VERSION_MINOR}+ を有効化してから再実行してください。"
      exit 1
    fi
    echo "[setup] 現在アクティブな仮想環境 ($VIRTUAL_ENV) を使用します。"
  else
    if [ -d "$VENV_DIR" ]; then
      ACTIVE_PYTHON=$(python_from_venv "$VENV_DIR")
      if [ -z "$ACTIVE_PYTHON" ]; then
        echo "[setup] 既存の $VENV_DIR が壊れています。再作成します。"
        rm -rf "$VENV_DIR"
      elif ! python_supports_required_version "$ACTIVE_PYTHON"; then
        version=$(python_version_string "$ACTIVE_PYTHON")
        echo "[setup] 既存の $VENV_DIR は Python ${version} です。Python ${PYTHON_MIN_VERSION_MAJOR}.${PYTHON_MIN_VERSION_MINOR}+ へ再作成します。"
        rm -rf "$VENV_DIR"
      fi
    fi

    if [ ! -d "$VENV_DIR" ]; then
      PYTHON_BOOTSTRAP=$(choose_python_bin) || {
        echo "[setup] Python ${PYTHON_MIN_VERSION_MAJOR}.${PYTHON_MIN_VERSION_MINOR}+ を見つけられませんでした。環境に導入してから再実行してください。"
        exit 1
      }
      echo "[setup] $(basename "$PYTHON_BOOTSTRAP") で $VENV_DIR を作成します。"
      "$PYTHON_BOOTSTRAP" -m venv "$VENV_DIR"
    fi

    # 作りたて/既存どちらでもactivate
    # shellcheck disable=SC1090
    . "$VENV_DIR/bin/activate"
    ACTIVE_PYTHON=$(python_from_venv "$VENV_DIR")
  fi

  if [ -z "$ACTIVE_PYTHON" ]; then
    echo "[setup] Python 実行ファイルを特定できませんでした。"
    exit 1
  fi

  "$ACTIVE_PYTHON" -m pip install -U pip wheel
  "$ACTIVE_PYTHON" -m pip install -r backend/requirements.txt
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
