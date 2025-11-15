import os
import time
from typing import List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from loguru import logger

from backend.core.boot import BootResult, run_boot_checks, get_boot_cache
from backend.api.routes import router as api_router
from backend.api.auth import router as auth_router
from backend.api.ws import ws_router, get_recent_stream_stats
from backend.api.google_sync import router as google_sync_router
from backend.store.db import init_db

LOG_DIR = os.getenv("LOG_DIR", "backend/data")
os.makedirs(LOG_DIR, exist_ok=True)
logger.add(os.path.join(LOG_DIR, "app.log"), rotation="10 MB", retention=5)

app = FastAPI(title="M4-Meet", version="0.1.0")
app.include_router(auth_router, prefix="")
app.include_router(api_router, prefix="")
app.include_router(google_sync_router, prefix="")
app.include_router(ws_router)


def _log_runtime_config() -> None:
    cfg = {
        "batch_whisper": os.getenv("M4_BATCH_WHISPER", "off"),
        "batch_translate": os.getenv("M4_BATCH_TRANSLATE", "off"),
        "fw_model": os.getenv("FW_MODEL") or os.getenv("M4_WHISPER_MODEL", ""),
        "fw_device": os.getenv("FW_DEVICE") or os.getenv("M4_WHISPER_DEVICE", ""),
        "fw_compute": os.getenv("FW_COMPUTE") or os.getenv("M4_WHISPER_COMPUTE", ""),
        "asr_kind": os.getenv("M4_ASR_KIND", ""),
    }
    conf_line = " ".join(f"{k}={cfg.get(k) or '-'}" for k in sorted(cfg))
    logger.bind(tag="startup.config").info(f"CONF {conf_line}")

def _build_allowed_origins() -> List[str]:
    raw = os.getenv("M4_CORS_ORIGINS", "")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    # 推奨: devサーバやPreviewのために localhost 系を自動登録
    fallback_ports = [
        os.getenv("DEV_FRONTEND_PORT"),
        os.getenv("PORT_FRONTEND"),
        "5173",
    ]
    fallback_hosts = ["127.0.0.1", "localhost"]
    for host in fallback_hosts:
        for port in fallback_ports:
            if port and port.strip():
                origins.append(f"http://{host}:{port.strip()}")
        origins.append(f"http://{host}")
    # すべての空文字/重複を除く
    cleaned = sorted({origin for origin in origins if origin})
    return cleaned

ALLOWED_ORIGINS = _build_allowed_origins()
if not ALLOWED_ORIGINS:
    # 最低限 localhost:5173 を許可
    ALLOWED_ORIGINS = ["http://127.0.0.1:5173", "http://localhost:5173"]

logger.bind(tag="startup.cors").info(f"CORS allow_origins={ALLOWED_ORIGINS}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSION_SECRET = os.getenv("SESSION_SECRET") or os.getenv("M4_SESSION_SECRET") or os.getenv("SECRET_KEY") or "change-me"
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site=os.getenv("SESSION_COOKIE_SAMESITE", "lax"),
    https_only=os.getenv("SESSION_COOKIE_SECURE", "0").strip().lower() in {"1","true","yes"},
)


class Health(BaseModel):
    ok: bool


@app.on_event("startup")
async def on_startup() -> None:
    logger.bind(tag="startup.init").info("initializing database and boot checks")
    await init_db()
    run_boot_checks(force=True)
    _log_runtime_config()


@app.get("/healthz", response_model=Health)
async def healthz():
    return Health(ok=True)


@app.get("/healthz/ready")
async def healthz_ready():
    br: BootResult = get_boot_cache()
    return JSONResponse(content={"ok": br.ok, "checks": br.checks})

# Compatibility aliases for common probes
@app.get("/health", response_model=Health)
async def health_alias():
    return await healthz()

@app.get("/ready")
async def ready_alias():
    return await healthz_ready()


@app.get("/api/health/models")
async def health_models():
    """モデル健診: ファイル存在・I/O名・16k要件を個別チェック"""
    import glob
    import os
    from typing import Dict, List
    import shutil
    
    def _check_model_file(name: str, path: str, check_onnx: bool = True) -> Dict:
        result = {"name": name, "path": path, "ok": False, "issues": []}
        
        # ファイル存在チェック
        if not path or not os.path.exists(path):
            result["issues"].append("ファイルが見つかりません")
            return result
            
        # ファイルサイズチェック
        try:
            size = os.path.getsize(path)
            if size < 1000:  # 1KB未満
                result["issues"].append("ファイルサイズが小さすぎます")
                return result
        except Exception:
            result["issues"].append("ファイルサイズを取得できません")
            return result
        
        # ONNX形状チェック (簡易)
        if check_onnx and path.endswith('.onnx'):
            try:
                import onnxruntime as ort
                sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
                inputs = sess.get_inputs()
                outputs = sess.get_outputs()
                result["inputs"] = [{"name": inp.name, "shape": inp.shape} for inp in inputs]
                result["outputs"] = [{"name": out.name, "shape": out.shape} for out in outputs]
            except Exception as e:
                result["issues"].append(f"ONNX読み込みエラー: {str(e)}")
                return result
        
        # 問題なし
        result["ok"] = True
        return result
    
    def _glob_one(base_dir: str, patterns: List[str]) -> str:
        if not base_dir:
            return ""
        for pat in patterns:
            m = glob.glob(os.path.join(base_dir, "**", pat), recursive=True)
            if m:
                return m[0]
        return ""

    def _check_emb_dir(name: str, path: str) -> Dict:
        result = {"name": name, "path": path, "ok": False, "issues": []}
        if not path:
            result["issues"].append("ディレクトリが設定されていません")
            return result
        if not os.path.isdir(path):
            result["issues"].append("ディレクトリが見つかりません")
            return result
        required = ["hyperparams.yaml"]
        missing = [fname for fname in required if not os.path.exists(os.path.join(path, fname))]
        if missing:
            result["issues"].append(f"必要ファイルが不足: {', '.join(missing)}")
            return result
        result["ok"] = True
        result["files"] = sorted(os.listdir(path))
        return result
    
    checks = []
    
    # ASR チェック
    asr_dir = os.getenv("M4_ASR_DIR", "")
    asr_kind = os.getenv("M4_ASR_KIND", "").strip().lower()
    asr_tokens = os.getenv("M4_ASR_TOKENS", "") or _glob_one(asr_dir, ["tokens.txt"])
    if asr_kind in ("sense-voice", "sense_voice", "sensevoice", "sense-voice-offline", "sense_voice_offline", "sensevoice-offline"):
        asr_model = os.getenv("M4_ASR_MODEL", "") or _glob_one(asr_dir, ["model.int8.onnx", "model.onnx"])
        checks.append(_check_model_file("ASR tokens", asr_tokens, check_onnx=False))
        checks.append(_check_model_file("ASR model", asr_model, check_onnx=True))
    elif asr_kind in ("whisper-ct2", "whisper_ct2", "whisper", "faster-whisper", "faster_whisper"):
        whisper_model = os.getenv("M4_WHISPER_MODEL", "small")
        checks.append({
            "name": "ASR whisper model",
            "path": whisper_model,
            "ok": bool(whisper_model),
            "issues": ([] if whisper_model else ["M4_WHISPER_MODEL が設定されていません"]),
        })
    else:
        asr_encoder = os.getenv("M4_ASR_ENCODER", "") or _glob_one(asr_dir, ["encoder*.onnx"])
        asr_decoder = os.getenv("M4_ASR_DECODER", "") or _glob_one(asr_dir, ["decoder*.onnx"])
        asr_joiner = os.getenv("M4_ASR_JOINER", "") or _glob_one(asr_dir, ["joiner*.onnx"])
        checks.append(_check_model_file("ASR tokens", asr_tokens, check_onnx=False))
        checks.append(_check_model_file("ASR encoder", asr_encoder, check_onnx=True))
        checks.append(_check_model_file("ASR decoder", asr_decoder, check_onnx=True))
        checks.append(_check_model_file("ASR joiner", asr_joiner, check_onnx=True))
    
    # 話者分離チェック
    diar_dir = os.getenv("M4_DIAR_DIR", "")
    diar_seg_kind = os.getenv("M4_DIAR_SEG_KIND", "").strip().lower()
    diar_seg = os.getenv("M4_DIAR_SEG", "") or _glob_one(diar_dir, ["model.int8.onnx", "model.onnx"])
    diar_emb_dir = os.getenv("M4_DIAR_EMB_DIR", "").strip()
    diar_emb = os.getenv("M4_DIAR_EMB", "") or _glob_one(diar_dir, ["nemo_en_titanet_small.onnx", "embedding.onnx"])

    if diar_seg_kind in {"", "auto", "default"}:
        checks.append(_check_model_file("話者分離 segmentation", diar_seg, check_onnx=True))
    elif diar_seg_kind in {"none", "off"}:
        checks.append({
            "name": "話者分離 segmentation",
            "path": diar_seg_kind or "none",
            "ok": True,
            "issues": [],
        })
    else:
        checks.append(_check_model_file("話者分離 segmentation", diar_seg, check_onnx=True))

    if diar_emb_dir:
        checks.append(_check_emb_dir("話者分離 embedding", diar_emb_dir))
    else:
        checks.append(_check_model_file("話者分離 embedding", diar_emb, check_onnx=True))

    # LLM (llama.cpp / Ollama) チェック: プロバイダに応じて必要なものだけを検査
    llm_provider = os.getenv("M4_LLM_PROVIDER", "").strip().lower()
    if llm_provider in ("ollama",):
        # Ollama のみ検査
        ollama_base = (os.getenv("M4_OLLAMA_BASE", "").strip() or "http://127.0.0.1:11434")
        import httpx
        ok = False
        reason = ""
        url = ollama_base.rstrip('/') + "/v1/models"
        try:
            r = httpx.get(url, timeout=3.0)
            ok = r.status_code < 500
            reason = f"HTTP {r.status_code}"
        except Exception as e:
            ok = False
            reason = str(e)
        checks.append({
            "name": "Ollama API",
            "path": url,
            "ok": ok,
            "issues": ([] if ok else [f"疎通失敗: {reason}"])
        })
    else:
        # llama.cpp を検査
        llm_bin_env = os.getenv("M4_LLM_BIN", "")
        llm_bin = shutil.which(llm_bin_env) or shutil.which("llama-cli") or shutil.which("llama") or ""
        llm_model = os.getenv("M4_LLM_MODEL", "")
        checks.append({
            "name": "LLM binary",
            "path": llm_bin_env or "(auto: llama/llama-cli)",
            "resolved": llm_bin or "",
            "ok": bool(llm_bin),
            "issues": ([] if llm_bin else ["llama バイナリが見つかりません (brew の場合 'llama' です)"])
        })
        checks.append(_check_model_file("LLM model", llm_model, check_onnx=False))


    # 翻訳(CT2) チェック: バッチ翻訳が有効な場合のみ
    batch_translate = os.getenv("M4_BATCH_TRANSLATE", "off").strip().lower()
    if batch_translate not in ("0", "off", "false", ""):
        ct2_dir = os.getenv("M4_CT2_DIR", "")
        checks.append({
            "name": "CT2 dir",
            "path": ct2_dir,
            "ok": bool(ct2_dir and os.path.isdir(ct2_dir)),
            "issues": ([] if (ct2_dir and os.path.isdir(ct2_dir)) else ["ディレクトリが存在しません"])
        })
    
    # 全体判定
    all_ok = all(check.get("ok", False) for check in checks)

    return {
        "ok": all_ok,
        "checks": checks,
        "summary": f"{sum(1 for c in checks if c['ok'])}/{len(checks)} モデルが利用可能"
    }


@app.get("/api/health/recent")
async def health_recent():
    """直近のWSストリーム統計を返して診断に使う。"""
    return {"streams": get_recent_stream_stats()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT_BACKEND", "8000")))
