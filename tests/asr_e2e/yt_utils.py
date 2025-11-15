from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

try:
    from youtube_transcript_api import (
        YouTubeTranscriptApi,
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
    )
except ImportError as exc:
    raise SystemExit("youtube-transcript-api が見つかりません。tests/asr_e2e/requirements-optional.txt をインストールしてください") from exc

try:
    from yt_dlp import YoutubeDL
except ImportError as exc:
    raise SystemExit("yt-dlp が見つかりません。tests/asr_e2e/requirements-optional.txt をインストールしてください") from exc

__all__ = ["extract_video_id", "fetch_transcript"]

LANG_PRIORITIES: List[List[str]] = [
    ["ja"],
    ["ja-JP"],
    ["ja-Hira"],
    ["ja", "ja-JP"],
]


def extract_video_id(url_or_id: str) -> str:
    """Extract the 11-character YouTube video id from various URL forms."""
    candidate = url_or_id.strip()
    if not candidate:
        raise ValueError("YouTubeのURLまたは動画IDを指定してください")

    if re.fullmatch(r"[0-9A-Za-z_-]{11}", candidate):
        return candidate

    parsed = urlparse(candidate)
    if parsed.netloc.endswith("youtu.be"):
        vid = parsed.path.lstrip("/")
        if re.fullmatch(r"[0-9A-Za-z_-]{11}", vid):
            return vid
    if parsed.netloc.endswith("youtube.com") or parsed.netloc.endswith("youtube-nocookie.com"):
        if parsed.path == "/watch":
            qs = parse_qs(parsed.query)
            vid_list = qs.get("v") or []
            for vid in vid_list:
                if re.fullmatch(r"[0-9A-Za-z_-]{11}", vid):
                    return vid
        parts = parsed.path.split("/")
        for part in parts[::-1]:
            if re.fullmatch(r"[0-9A-Za-z_-]{11}", part):
                return part

    raise ValueError(f"動画IDを抽出できませんでした: {url_or_id}")


def _compile_text(entries: List[Dict[str, str]]) -> str:
    lines: List[str] = []
    for item in entries:
        text = getattr(item, "text", None)
        if text is None and isinstance(item, dict):
            text = item.get("text", "")
        if text is None:
            text = ""
        text = text.strip()
        if not text:
            continue
        lines.append(" ".join(text.splitlines()))
    return "\n".join(lines).strip()


def _try_fetch(transcripts, languages: List[str], prefer_manual: bool):
    try:
        if prefer_manual:
            transcript = transcripts.find_manually_created_transcript(languages)
        else:
            transcript = transcripts.find_generated_transcript(languages)
        entries = transcript.fetch()
        return {
            "text": _compile_text(entries),
            "language": transcript.language,
            "is_generated": transcript.is_generated,
            "was_translated": False,
            "source": "manual" if not transcript.is_generated else "auto",
        }
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
        return None


def _fetch_via_translation(transcripts):
    for transcript in transcripts:
        if not transcript.is_translatable:
            continue
        try:
            translated = transcript.translate("ja")
            entries = translated.fetch()
            text = _compile_text(entries)
            if text:
                return {
                    "text": text,
                    "language": translated.language,
                    "is_generated": transcript.is_generated,
                    "was_translated": True,
                    "source": "translated",
                }
        except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
            continue
    return None


def _parse_vtt(path: Path) -> str:
    lines: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("WEBVTT"):
            continue
        if "-->" in stripped:
            continue
        if stripped.isdigit():
            continue
        lines.append(stripped)
    return "\n".join(lines).strip()


def _fetch_via_yt_dlp(url: str) -> Optional[Dict[str, Optional[str]]]:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["ja"],
            "subtitlesformat": "vtt",
            "outtmpl": str(tmp / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        opts["extractor_args"] = {"youtube": {"player_client": ["android"]}}
        with YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(url, download=True)
            except Exception:
                return None
        pattern = re.compile(rf"{re.escape(info['id'])}\.ja.*\.vtt$")
        for path in tmp.glob("*.vtt"):
            if pattern.match(path.name):
                text = _parse_vtt(path)
                if text:
                    return {
                        "text": text,
                        "language": "ja",
                        "is_generated": True,
                        "was_translated": False,
                        "source": "yt_dlp_auto",
                    }
    return None


def fetch_transcript(video_id: str, *, url: str | None = None) -> Dict[str, Optional[str]]:
    """Fetch a Japanese transcript (manual>auto>translated>yt-dlp-auto) for a given video id."""
    api = YouTubeTranscriptApi()
    try:
        transcripts = api.list(video_id)
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable) as exc:
        if url:
            fallback = _fetch_via_yt_dlp(url)
            if fallback:
                return fallback
        raise RuntimeError(f"動画の字幕を取得できませんでした: {exc}") from exc

    for langs in LANG_PRIORITIES:
        result = _try_fetch(transcripts, langs, prefer_manual=True)
        if result and result["text"]:
            return result

    for langs in LANG_PRIORITIES:
        result = _try_fetch(transcripts, langs, prefer_manual=False)
        if result and result["text"]:
            return result

    translated = _fetch_via_translation(transcripts)
    if translated:
        return translated

    if url:
        fallback = _fetch_via_yt_dlp(url)
        if fallback:
            return fallback

    raise RuntimeError("日本語の字幕（生成含む）を取得できませんでした")
