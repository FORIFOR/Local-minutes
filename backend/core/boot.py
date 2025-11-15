import os
import shutil
from dataclasses import dataclass
from typing import Dict, List, Optional


_boot_cache = None


@dataclass
class BootResult:
    ok: bool
    checks: List[Dict]


def _check_path(name: str, path: str, must_exist: bool = True, executable: bool = False, min_bytes: Optional[int] = None) -> Dict:
    status = True
    reason = None
    p = os.path.expanduser(os.path.expandvars(path)) if path else ""

    if executable:
        # 実行ファイルは (1) 絶対/相対パスで実行可能 もしくは (2) PATH で検出 のどちらかを許容
        is_exec = bool(p) and os.path.isfile(p) and os.access(p, os.X_OK)
        in_path = shutil.which(p) is not None
        if not (is_exec or in_path):
            status = False
            reason = f"not executable or not found in PATH: {p}"
    else:
        if must_exist and not (p and os.path.exists(p)):
            status = False
            reason = f"missing: {p}"

    # NOTE: サイズ検査は省略 (存在/実行可能性のみ)
    return {"name": name, "ok": status, "path": p, "reason": reason}


def _check_disk_space(path: str, need_gb: int) -> Dict:
    p = os.path.expanduser(os.path.expandvars(path)) if path else "."
    reason = None
    try:
        if not os.path.exists(p):
            # フォールバック: 存在しない場合はカレントでチェック
            reason = f"missing: {p}; fallback to '.'"
            p = "."
        st = shutil.disk_usage(p)
        free_gb = st.free / (1024**3)
        ok = free_gb >= need_gb
        return {"name": "disk.space", "ok": ok, "free_gb": round(free_gb, 2), "need_gb": need_gb, "path": p, "reason": reason}
    except Exception as e:
        # 取得不能でも起動は継続（警告）
        return {"name": "disk.space", "ok": True, "free_gb": -1, "need_gb": need_gb, "path": p, "reason": str(e)}


def run_boot_checks(force: bool = False) -> BootResult:
    global _boot_cache
    if _boot_cache is not None and not force:
        return _boot_cache

    checks: List[Dict] = []
    models_dir = os.getenv("M4_MODELS_DIR", "")
    asr_dir = os.getenv("M4_ASR_DIR", "")
    diar_dir = os.getenv("M4_DIAR_DIR", "")
    llm_bin = os.getenv("M4_LLM_BIN", "llama-cli")
    llm_model = os.getenv("M4_LLM_MODEL", "")
    ct2_dir = os.getenv("M4_CT2_DIR", "")
    tts_voice = os.getenv("M4_TTS_VOICE", "")
    log_dir = os.getenv("LOG_DIR", "backend/data")

    # base dirs and space
    checks.append(_check_path("models.dir", models_dir))
    checks.append(_check_disk_space(models_dir or ".", 8))

    # ASR required files
    import glob
    def _glob_one(patterns):
        for pat in patterns:
            m = glob.glob(os.path.join(asr_dir, "**", pat), recursive=True)
            if m:
                return m[0]
        return None

    asr_kind = os.getenv("M4_ASR_KIND", "transducer").strip().lower()
    if asr_kind in (
        "sense-voice",
        "sense_voice",
        "sensevoice",
        "sense-voice-offline",
        "sense_voice_offline",
        "sensevoice-offline",
    ):
        asr_tokens = os.getenv("M4_ASR_TOKENS", "") or _glob_one(["tokens.txt"]) or ""
        asr_model = os.getenv("M4_ASR_MODEL", "") or _glob_one(["model.int8.onnx", "model.onnx"]) or ""
        checks.append(_check_path("asr.tokens", asr_tokens))
        checks.append(_check_path("asr.model", asr_model))
    elif asr_kind in (
        "whisper-ct2",
        "whisper_ct2",
        "whisper",
        "faster-whisper",
        "faster_whisper",
    ):
        whisper_model = os.getenv("M4_WHISPER_MODEL", "small")
        checks.append({
            "name": "asr.whisper.model",
            "path": whisper_model,
            "ok": bool(whisper_model),
            "issues": ([] if whisper_model else ["環境変数 M4_WHISPER_MODEL が未設定です"]),
        })
    else:
        asr_tokens = os.getenv("M4_ASR_TOKENS", "") or _glob_one(["tokens.txt"]) or ""
        asr_encoder = os.getenv("M4_ASR_ENCODER", "") or _glob_one(["encoder*.onnx"]) or ""
        asr_decoder = os.getenv("M4_ASR_DECODER", "") or _glob_one(["decoder*.onnx"]) or ""
        asr_joiner = os.getenv("M4_ASR_JOINER", "") or _glob_one(["joiner*.onnx"]) or ""
        checks.append(_check_path("asr.tokens", asr_tokens))
        checks.append(_check_path("asr.encoder", asr_encoder))
        checks.append(_check_path("asr.decoder", asr_decoder))
        checks.append(_check_path("asr.joiner", asr_joiner))

    # Diarization required files
    diar_seg = None
    for pat in ("model.int8.onnx", "model.onnx", "segmentation*.onnx"):
        m = glob.glob(os.path.join(diar_dir, "**", pat), recursive=True)
        if m:
            diar_seg = m[0]
            break
    diar_emb = None
    for pat in ("nemo_en_titanet_small.onnx", "embedding.onnx"):
        m = glob.glob(os.path.join(diar_dir, "**", pat), recursive=True)
        if m:
            diar_emb = m[0]
            break
    checks.append(_check_path("diar.seg", diar_seg or "", must_exist=True))
    checks.append(_check_path("diar.emb", diar_emb or "", must_exist=True))

    # LLM binary and model
    checks.append(_check_path("llm.bin", llm_bin, executable=True))
    checks.append(_check_path("llm.model", llm_model))

    # CT2 directory should contain model files
    checks.append(_check_path("ct2.dir", ct2_dir))

    # TTS voice onnx and json
    tts_json = os.path.splitext(tts_voice)[0] + ".onnx.json"
    checks.append(_check_path("tts.voice.onnx", tts_voice))
    checks.append(_check_path("tts.voice.json", tts_json))

    # Write permissions
    def _check_writable(name: str, path: str) -> Dict:
        ok = False
        reason = None
        p = os.path.expanduser(os.path.expandvars(path))
        try:
            os.makedirs(p, exist_ok=True)
            testf = os.path.join(p, ".wtest")
            with open(testf, "w") as f:
                f.write("ok")
            os.remove(testf)
            ok = True
        except Exception as e:
            ok = False
            reason = str(e)
        return {"name": name, "ok": ok, "path": p, "reason": reason}

    checks.append(_check_writable("writable.log_dir", log_dir))
    checks.append(_check_writable("writable.data", os.path.join("backend", "data")))
    checks.append(_check_writable("writable.artifacts", os.path.join("backend", "artifacts")))

    # 重要度に応じて緩和した判定を採用
    asr_kind = os.getenv("M4_ASR_KIND", "transducer").strip().lower()
    critical_names = {
        "writable.log_dir",
        "writable.data",
        "writable.artifacts",
    }
    if asr_kind in ("sense-voice", "sense_voice", "sensevoice"):
        critical_names |= {"asr.tokens", "asr.model"}
    else:
        critical_names |= {"asr.tokens", "asr.encoder", "asr.decoder", "asr.joiner"}

    ok_critical = True
    for c in checks:
        if c.get("name") in critical_names and not c.get("ok"):
            ok_critical = False
            break

    _boot_cache = BootResult(ok=ok_critical, checks=checks)

    # 環境変数で厳格モードを切替（既定は寛容に起動継続）
    strict = os.getenv("M4_STRICT_BOOT", "0").lower() in ("1", "true", "yes")
    if strict and not ok_critical:
        import sys
        print({"ok": ok_critical, "checks": checks})
        sys.exit(1)

    return _boot_cache


def get_boot_cache() -> BootResult:
    return _boot_cache or run_boot_checks(force=False)
