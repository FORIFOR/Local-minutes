import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


def run_fluidaudio(
    wav_path: Path,
    out_json: Path,
    bin_path: str,
    *,
    threshold: float = 0.6,
    mode: str = "offline",
) -> Dict[str, Any]:
    if not wav_path.exists() or wav_path.stat().st_size < 4000:
        raise FileNotFoundError(f"audio not found or too small: {wav_path}")

    exe = shutil.which(bin_path) or bin_path
    cmd = [
        exe,
        "process",
        str(wav_path),
        "--mode",
        mode,
        "--threshold",
        str(threshold),
        "--output",
        str(out_json),
    ]
    logger.bind(tag="diar.batch").info("fluidaudio", cmd=" ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"fluidaudio failed: {result.stderr.strip()}")
    try:
        data = json.loads(out_json.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"failed to parse {out_json}: {exc}")
    return data


def _normalize_diar_segments(diar: Dict[str, Any]) -> List[Dict[str, Any]]:
    segments: List[Dict[str, Any]] = []
    raw = diar.get("segments") or diar.get("results") or []
    for item in raw:
        start = item.get("start") or item.get("startTimeSeconds") or item.get("start_time")
        end = item.get("end") or item.get("endTimeSeconds") or item.get("end_time")
        if start is None or end is None:
            continue
        speaker = (
            item.get("speaker")
            or item.get("speakerId")
            or item.get("speaker_id")
            or item.get("cluster")
            or "S?"
        )
        segments.append({"start": float(start), "end": float(end), "speaker": str(speaker)})
    segments.sort(key=lambda s: s["start"])
    return segments


def attach_speakers_to_whisper(whisper_json: Dict[str, Any], diar_json: Dict[str, Any]) -> Dict[str, Any]:
    diar_segments = _normalize_diar_segments(diar_json)
    segments = whisper_json.get("segments", [])

    def lookup(t: float) -> str:
        for seg in diar_segments:
            if seg["start"] - 0.05 <= t <= seg["end"] + 0.05:
                return seg["speaker"]
        if not diar_segments:
            return "S?"
        # fallback: nearest center
        target = min(diar_segments, key=lambda seg: abs(((seg["start"] + seg["end"]) / 2) - t))
        return target["speaker"]

    for seg in segments:
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        words = seg.get("words") or []
        if words:
            for w in words:
                w_start = float(w.get("start", start))
                w_end = float(w.get("end", w_start))
                mid = (w_start + w_end) / 2.0
                w["speaker"] = lookup(mid)
            seg["speaker"] = words[0].get("speaker", "S?")
        else:
            mid = (start + end) / 2.0
            seg["speaker"] = lookup(mid)

    whisper_json["diarization"] = {
        "engine": "fluidaudio",
        "segments": diar_segments,
    }
    return whisper_json


def build_minutes_text(segments: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    last_speaker: Optional[str] = None
    buffer: List[str] = []

    def flush() -> None:
        if not buffer or last_speaker is None:
            return
        text = " ".join(buffer).strip()
        if not text:
            return
        lines.append(f"{last_speaker}: {text}")
        buffer.clear()

    for seg in segments:
        speaker = seg.get("speaker") or "S?"
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if last_speaker is None:
            last_speaker = speaker
        if speaker != last_speaker:
            flush()
            last_speaker = speaker
        buffer.append(text)
    flush()
    return "\n".join(lines)
