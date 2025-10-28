import os
import json
import subprocess
from loguru import logger
from backend.store.files import artifact_path_for_event
from backend.store import db


def _should_run() -> bool:
    """環境変数でバッチ処理のON/OFFを切替。
    既定値: off（必要時のみ M4_BATCH_WHISPER=on で有効化）
    """
    return (os.getenv("M4_BATCH_WHISPER", "off").strip().lower() not in ("0", "off", "false"))


def _transcribe_faster_whisper(src_wav: str, out_json: str) -> None:
    """faster-whisper で停止後の軽量整形を実行（完全ローカル）。
    必要ライブラリは import 時にロード（未導入でも他経路に影響しない）。
    """
    from faster_whisper import WhisperModel  # type: ignore

    model_name = os.getenv("M4_WHISPER_MODEL", "small")
    device = os.getenv("M4_WHISPER_DEVICE", "cpu")
    compute = os.getenv("M4_WHISPER_COMPUTE", "int8_float16")
    threads = int(os.getenv("M4_WHISPER_THREADS", "4"))
    beam = int(os.getenv("M4_WHISPER_BEAM", "1"))
    use_vad = os.getenv("M4_WHISPER_VAD", "1").strip() not in ("0", "off", "false")

    logger.bind(tag="asr.batch").info(
        f"faster-whisper model={model_name} device={device} compute={compute} threads={threads} beam={beam} vad={use_vad}"
    )
    model = WhisperModel(model_name, device=device, compute_type=compute, cpu_threads=threads, num_workers=1)
    segments, info = model.transcribe(
        src_wav,
        beam_size=beam,
        vad_filter=use_vad,
        vad_parameters=dict(min_silence_duration_ms=300),
        condition_on_previous_text=False,
        language="ja",
    )
    out = {
        "language": info.language,
        "segments": [
            {"start": float(s.start), "end": float(s.end), "text": s.text}
            for s in segments
        ],
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)


def run_batch_retranscribe(event_id: str) -> None:
    # バッチ無効時は即停止
    if not _should_run():
        logger.bind(tag="asr.batch").info("batch whisper is disabled (M4_BATCH_WHISPER=off)")
        return
    # 停止後の全文書き起こし（現行は CLI or faster-whisper の2択）
    # 音声取得: ライブストリームの保存は別途、ここでは event_id.wav がある前提 or 未実装ならスキップ
    src_wav = artifact_path_for_event(event_id, "record.wav")
    # 最低ヘッダサイズ(~44B) + 数KB以上の実データが無ければスキップ
    if not os.path.exists(src_wav) or os.path.getsize(src_wav) < 4000:
        logger.bind(tag="asr.batch").warning(f"no audio for {event_id}, skip batch")
        return
    out_json = artifact_path_for_event(event_id, "whisper.json")
    backend = os.getenv("M4_WHISPER_BACKEND", "insanely-fast").strip().lower()
    if backend in ("faster-whisper", "faster", "ct2"):
        _transcribe_faster_whisper(src_wav, out_json)
        with open(out_json, "r", encoding="utf-8") as f:
            j = json.load(f)
    else:
        # insanely-fast-whisper CLI 経由（既定）
        device_id = os.getenv("IFW_DEVICE_ID", "mps")
        model_name = os.getenv("IFW_MODEL_NAME", "openai/whisper-large-v3")
        task = os.getenv("IFW_TASK", "transcribe")
        cmd = [
            "insanely-fast-whisper",
            "--file-name", src_wav,
            "--device-id", device_id,
            "--transcript-path", out_json,
            "--language", "ja",
            "--model-name", model_name,
            "--task", task,
        ]
        logger.bind(tag="asr.batch").info(" ".join(cmd))
        subprocess.run(cmd, check=True)
        with open(out_json, "r", encoding="utf-8") as f:
            j = json.load(f)
    segs = j.get("segments", [])
    import asyncio
    async def _import():
        for s in segs:
            await db.insert_segment(event_id, float(s["start"]), float(s["end"]), s.get("speaker","S1"), s.get("text",""), "", "batch")
    asyncio.run(_import())
