import asyncio
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from backend.store.files import artifact_path_for_event
from backend.store import db, minutes_repo


def _should_run() -> bool:
    """環境変数でバッチ処理のON/OFFを切替。
    既定値: off（必要時のみ M4_BATCH_WHISPER=on で有効化）
    """
    return (os.getenv("M4_BATCH_WHISPER", "off").strip().lower() not in ("0", "off", "false"))


def _transcribe_with_faster_whisper(src_wav: str, out_json: str) -> Dict[str, Any]:
    """faster-whisper を用いてローカルで再転記する。"""
    from faster_whisper import WhisperModel  # type: ignore

    model_name = os.getenv("M4_WHISPER_MODEL", "large-v3")
    device = os.getenv("M4_WHISPER_DEVICE", "auto")
    compute = os.getenv("M4_WHISPER_COMPUTE", "int8")
    threads = int(os.getenv("M4_WHISPER_THREADS", "4"))
    beam = int(os.getenv("M4_WHISPER_BEAM", "5"))
    use_vad = os.getenv("M4_WHISPER_VAD", "1").strip().lower() not in ("0", "off", "false")

    logger.bind(tag="asr.batch").info(
        "faster-whisper offline decode",
        model=model_name,
        device=device,
        compute=compute,
        beam=beam,
        vad=use_vad,
    )
    model = WhisperModel(model_name, device=device, compute_type=compute, cpu_threads=threads, num_workers=1)
    segments, info = model.transcribe(
        src_wav,
        beam_size=beam,
        vad_filter=use_vad,
        vad_parameters=dict(min_silence_duration_ms=300),
        condition_on_previous_text=False,
        language="ja",
        initial_prompt=_load_prompt(),
    )
    seg_list = [
        {"start": float(s.start), "end": float(s.end), "text": s.text}
        for s in segments
    ]
    text = "".join(seg["text"] for seg in seg_list).strip()
    out = {"language": info.language, "segments": seg_list, "text": text}
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    return out


def _load_prompt() -> Optional[str]:
    prompt_path = os.getenv("M4_INITIAL_PROMPT_FILE", "").strip()
    if prompt_path and os.path.exists(prompt_path):
        try:
            return (open(prompt_path, "r", encoding="utf-8").read() or "").strip() or None
        except OSError:
            logger.bind(tag="asr.batch").warning("failed to read prompt file", path=prompt_path)
    return None


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
    result = _transcribe_with_faster_whisper(src_wav, out_json)
    segments = result.get("segments", [])

    def _audio_duration(path: str) -> float:
        try:
            import wave

            with wave.open(path, "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate() or 16000
                if rate <= 0:
                    return 0.0
                return frames / float(rate)
        except Exception:
            return 0.0

    audio_sec = _audio_duration(src_wav)
    intervals: List[Tuple[float, float]] = []
    for seg in segments:
        try:
            st = float(seg.get("start", 0.0))
            ed = float(seg.get("end", st))
        except (TypeError, ValueError):
            continue
        if ed <= st:
            continue
        if audio_sec > 0:
            st = max(0.0, st)
            ed = min(audio_sec, ed)
        if ed <= st:
            continue
        intervals.append((st, ed))
    intervals.sort()
    covered = 0.0
    cur_start = None
    cur_end = None
    for st, ed in intervals:
        if cur_start is None:
            cur_start, cur_end = st, ed
            continue
        if st <= cur_end + 1e-3:
            cur_end = max(cur_end, ed)
        else:
            covered += cur_end - cur_start
            cur_start, cur_end = st, ed
    if cur_start is not None and cur_end is not None:
        covered += cur_end - cur_start
    coverage_ratio = (covered / audio_sec) if audio_sec > 0 else (1.0 if segments else 0.0)

    min_segments = int(os.getenv("M4_WHISPER_MIN_SEGMENTS", "1") or "1")
    min_text_chars = int(os.getenv("M4_WHISPER_MIN_CHARS", "20") or "20")
    min_cover_ratio = float(os.getenv("M4_WHISPER_MIN_COVERAGE", "0.6") or "0.6")
    total_chars = len((result.get("text") or "").strip())

    if not segments or len(segments) < min_segments or total_chars < min_text_chars or coverage_ratio < min_cover_ratio:
        logger.bind(tag="asr.batch").warning(
            "whisper batch insufficient output; keep live segments",
            segments=len(segments),
            chars=total_chars,
            coverage=f"{coverage_ratio:.2f}",
            audio_sec=f"{audio_sec:.2f}",
        )
        return

    async def _import():
        # ライブ書き起こしはバッチ結果で置き換える
        await db.delete_segments(event_id, origins=("live", "batch"))
        for s in segments:
            await db.insert_segment(
                event_id,
                float(s.get("start", 0.0)),
                float(s.get("end", s.get("start", 0.0))),
                s.get("speaker", "S1"),
                s.get("text", "") or "",
                "",
                "batch",
            )

    asyncio.run(_import())

    text_body = (result.get("text") or "").strip()
    autofill = os.getenv("M4_AUTOFILL_MINUTES", "off").strip().lower() not in ("0", "off", "false", "")
    if text_body and autofill:
        async def _upsert():
            await minutes_repo.upsert(event_id, body=text_body)

        asyncio.run(_upsert())
        logger.bind(tag="asr.batch").info("minutes autofilled from batch result", event=event_id, chars=len(text_body))
    else:
        logger.bind(tag="asr.batch").info(
            "batch whisper complete", event=event_id, chars=len(text_body), autofill_enabled=autofill
        )
