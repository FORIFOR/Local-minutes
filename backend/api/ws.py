import asyncio
import os
import json
import time
import re
import unicodedata
from collections import deque
from difflib import SequenceMatcher
from typing import Optional, List, Dict, Tuple, Set
import contextlib
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from loguru import logger

from backend.store.db import validate_ws_token, insert_segment
from backend.store.files import artifact_path_for_event
from backend.asr import create_realtime_asr
from backend.diar.online_cluster import OnlineDiarizer
from backend.nlp.translate_ct2 import Translator


ws_router = APIRouter()

RECENT_STREAM_LIMIT = int(os.getenv("RECENT_STREAM_LIMIT", "20"))
RECENT_STREAM_STATS: List[Dict[str, object]] = []
RECENT_FINAL_WINDOW_SEC = float(os.getenv("RECENT_FINAL_WINDOW_S", "6.0"))
RECENT_FINAL_KEYS: deque[Tuple[str, float]] = deque()

_FALSEY = {"0", "false", "off", "no", ""}


def _env_truthy(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in _FALSEY


def get_recent_stream_stats() -> List[Dict[str, object]]:
    """Expose last few WS sessions for /api/health/recent."""
    return list(RECENT_STREAM_STATS)


def _remember_stream_stat(event_id: str, chunks: int, bytes_written: int, duration: float, status: str) -> None:
    RECENT_STREAM_STATS.append(
        {
            "event": event_id,
            "chunks": chunks,
            "bytes": bytes_written,
            "duration": round(duration, 2),
            "status": status,
            "ts": time.time(),
        }
    )
    if len(RECENT_STREAM_STATS) > RECENT_STREAM_LIMIT:
        RECENT_STREAM_STATS.pop(0)


def _normalize_final_key(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = re.sub(r"[\s、。，．,.!?！？ー\-〜…・]+", "", normalized)
    return normalized


def _remember_final_key(key: str) -> None:
    if not key:
        return
    RECENT_FINAL_KEYS.append((key, time.time()))
    _cleanup_final_keys()


def _cleanup_final_keys() -> None:
    now = time.time()
    limit = now - max(0.5, RECENT_FINAL_WINDOW_SEC)
    while RECENT_FINAL_KEYS and RECENT_FINAL_KEYS[0][1] < limit:
        RECENT_FINAL_KEYS.popleft()


def _is_recent_final_key(key: str) -> bool:
    if not key:
        return False
    _cleanup_final_keys()
    for existing, _ in RECENT_FINAL_KEYS:
        if existing == key:
            return True
    return False


def _serialize_partial(partial: object) -> Optional[Dict[str, object]]:
    if partial is None:
        return None
    if isinstance(partial, dict):
        payload = {
            "type": "partial",
            "text": partial.get("text") or "",
        }
        if "stable" in partial:
            payload["stable"] = partial.get("stable") or ""
        if "unstable" in partial:
            payload["unstable"] = partial.get("unstable") or ""
        if "latency_ms" in partial:
            payload["latency_ms"] = partial.get("latency_ms")
        return payload
    text = getattr(partial, "text", None)
    if isinstance(text, str):
        payload = {"type": "partial", "text": text}
        stable = getattr(partial, "stable", "")
        unstable = getattr(partial, "unstable", "")
        latency = getattr(partial, "latency_ms", None)
        if stable:
            payload["stable"] = stable
        if unstable:
            payload["unstable"] = unstable
        if latency is not None:
            payload["latency_ms"] = latency
        return payload
    if isinstance(partial, str):
        return {"type": "partial", "text": partial}



def _as_final_segment(segment: object) -> Optional[Tuple[float, float, str, Optional[bytes]]]:
    if not isinstance(segment, (tuple, list)):
        return None
    if len(segment) < 3:
        return None
    start, end, text = segment[:3]
    try:
        start_f = float(start)
        end_f = float(end)
    except (TypeError, ValueError):
        return None
    text_str = text if isinstance(text, str) else str(text)
    audio = segment[3] if len(segment) > 3 else None
    if isinstance(audio, memoryview):
        audio = audio.tobytes()
    elif isinstance(audio, bytearray):
        audio = bytes(audio)
    elif audio is not None and not isinstance(audio, bytes):
        try:
            audio = bytes(audio)
        except Exception:
            audio = None
    return (start_f, end_f, text_str, audio)


async def _safe_send_json(ws: WebSocket, payload: Dict[str, object]) -> bool:
    """WebSocketが有効な場合のみ送信し、失敗時はFalseを返す。"""
    if ws.application_state != WebSocketState.CONNECTED:
        logger.bind(tag="ws.stream").warning(f"safe_send drop type={payload.get('type')} state={ws.application_state}")
        return False
    try:
        await ws.send_json(payload)
        return True
    except RuntimeError as exc:
        logger.bind(tag="ws.stream").warning(f"safe_send failed: {exc}")
        return False


async def await_safe_send(ws: WebSocket, payload: Dict[str, object]) -> bool:
    """送信前に状態を確認し、切断済みならFalseを返す."""
    if ws.client_state != WebSocketState.CONNECTED:
        return False
    try:
        await ws.send_text(json.dumps(payload))
        return True
    except Exception as exc:
        logger.bind(tag="ws.stream").debug(f"safe_send_text drop: {exc}")
        return False


async def _keepalive(ws: WebSocket, stop_evt: asyncio.Event, interval: int = 15) -> None:
    """定期的にpingを送り接続状態を保つ。"""
    while not stop_evt.is_set():
        ok = await _safe_send_json(ws, {"type": "ping", "ts": time.time()})
        if not ok:
            break
        try:
            await asyncio.wait_for(stop_evt.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


def _segment_iou(a: Dict[str, float], b: Dict[str, float]) -> float:
    inter = max(0.0, min(a["t1"], b["t1"]) - max(a["t0"], b["t0"]))
    union = (a["t1"] - a["t0"]) + (b["t1"] - b["t0"]) - inter
    return inter / union if union > 0 else 0.0


def _text_similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


async def _safe_close_ws(ws: WebSocket, code: int = 1011) -> None:
    """WebSocketの状態を確認してから安全にcloseする。"""
    try:
        if ws.client_state in (WebSocketState.CONNECTING, WebSocketState.CONNECTED):
            await ws.close(code=code)
    except RuntimeError as close_err:
        # close送信済みの場合は無視。それ以外はログだけ残す
        if "close message has been sent" not in str(close_err).lower():
            logger.bind(tag="ws.stream").debug(f"safe_close_ws skipped: {close_err}")


@ws_router.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    await ws.accept()
    params = ws.scope.get("query_string", b"")
    from urllib.parse import parse_qs
    q = parse_qs(params.decode())
    event_id = q.get("event_id", [""])[0]
    token = q.get("token", [""])[0]

    if not await validate_ws_token(event_id, token):
        await ws.close(code=4403)
        return

    stop_evt = asyncio.Event()
    keepalive_task = asyncio.create_task(_keepalive(ws, stop_evt))

    # 録音保存先を準備 (16k/mono/PCM16)
    import wave
    wav_path = artifact_path_for_event(event_id, "record.wav")
    wav = wave.open(wav_path, "wb")
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(16000)
    # ヘッダーを書き出してファイルを確実に作成
    try:
        wav.writeframes(b"")
    except Exception:
        pass
    bytes_written = 0
    chunks = 0
    t_start = time.time()
    last_log = t_start
    logger.bind(tag="ws.stream").info(f"WS start event={event_id} record={wav_path}")

    sample_rate = 16000
    diar_buf_seconds = max(5, int(os.getenv("M4_DIAR_BUFFER_SECONDS", "30") or "30"))
    max_buffer_samples = diar_buf_seconds * sample_rate
    audio_buffer = bytearray()
    total_samples_written = 0

    def _append_audio(chunk: bytes) -> None:
        nonlocal total_samples_written, audio_buffer
        if not chunk:
            return
        audio_buffer.extend(chunk)
        total_samples_written += len(chunk) // 2
        max_bytes = max_buffer_samples * 2
        if len(audio_buffer) > max_bytes:
            drop = len(audio_buffer) - max_bytes
            drop -= drop % 2
            if drop > 0:
                del audio_buffer[:drop]

    def _extract_audio_segment(start_s: float, end_s: float) -> bytes:
        if end_s <= start_s:
            return b""
        buffer_samples = len(audio_buffer) // 2
        if buffer_samples == 0:
            return b""
        buffer_start_sample = max(0, total_samples_written - buffer_samples)
        start_sample = max(0, int(start_s * sample_rate))
        end_sample = max(start_sample + 1, int(end_s * sample_rate))
        offset_start = start_sample - buffer_start_sample
        offset_end = end_sample - buffer_start_sample
        if offset_end <= 0 or offset_start >= buffer_samples:
            return b""
        offset_start = max(0, offset_start)
        offset_end = min(buffer_samples, offset_end)
        byte_start = offset_start * 2
        byte_end = offset_end * 2
        return bytes(audio_buffer[byte_start:byte_end])

    last_final_segment: Optional[Dict[str, float]] = None
    last_row_id: Optional[int] = None
    next_row_id = 1

    async def emit_final(text: str, start_s: float, end_s: float, speaker: str, mt_text: str) -> None:
        nonlocal last_final_segment, last_row_id, next_row_id
        seg = {"t0": float(start_s), "t1": float(end_s), "text": text}
        if last_final_segment and last_row_id is not None:
            if _segment_iou(seg, last_final_segment) >= 0.6 and _text_similarity(seg["text"], last_final_segment["text"]) >= 0.8:
                await await_safe_send(
                    ws,
                    {
                        "type": "final-update",
                        "rowId": last_row_id,
                        "text": text,
                        "range": [seg["t0"], seg["t1"]],
                        "speaker": speaker,
                        "mt": mt_text,
                    },
                )
                last_final_segment = seg
                return
        row_id = next_row_id
        next_row_id += 1
        payload = {
            "type": "final",
            "rowId": row_id,
            "text": text,
            "range": [seg["t0"], seg["t1"]],
            "speaker": speaker,
            "mt": mt_text,
        }
        ok = await await_safe_send(ws, payload)
        if ok:
            last_final_segment = seg
            last_row_id = row_id

    # モデル初期化はバックグラウンドで実施（録音受信をブロックしない）
    asr = None
    diar = None
    mt = None
    seen_speakers: Set[str] = set()
    last_speaker = ""

    def _is_diar_ready() -> bool:
        return bool(diar) or bool(getattr(asr, "live_diar_enabled", False))

    async def _init_models():
        nonlocal asr, diar, mt
        try:
            logger.bind(tag="ws.stream").info("initializing ASR/diar/MT models in background")
            live_asr = _env_truthy("M4_ASR_LIVE", True)
            if live_asr:
                asr = create_realtime_asr()
            else:
                asr = None
                logger.bind(tag="ws.stream").info("ASR live disabled via env (M4_ASR_LIVE=off)")
            if _env_truthy("M4_ENABLE_DIAR_LIVE", True):
                try:
                    diar = OnlineDiarizer()
                    logger.bind(tag="ws.stream").info("live diarization enabled (M4_ENABLE_DIAR_LIVE=on)")
                except Exception as diar_err:
                    diar = None
                    logger.bind(tag="ws.stream").warning(f"live diarization unavailable: {diar_err}")
            else:
                diar = None
                logger.bind(tag="ws.stream").info("live diarization disabled via env (M4_ENABLE_DIAR_LIVE=off)")
            mt_kind = os.getenv("M4_MT_KIND", "on").strip().lower()
            if mt_kind and mt_kind != "off":
                try:
                    mt = Translator()
                except Exception as mt_err:
                    mt = None
                    logger.bind(tag="ws.stream").warning(f"translator unavailable: {mt_err}")
            else:
                mt = None
                logger.bind(tag="ws.stream").info("translator disabled via env (M4_MT_KIND=off)")
            logger.bind(tag="ws.stream").info("models ready: ASR/diar/MT initialized")
            try:
                if asr is not None:
                    await _safe_send_json(ws, {
                        "type": "warn",
                        "message": "ASR初期化完了。以降はライブ転記が有効です。"
                    })
                else:
                    await _safe_send_json(ws, {
                        "type": "warn",
                        "message": "ASRは無効化されています（録音のみ）。"
                    })
                await _safe_send_json(ws, {
                    "type": "stat",
                    "diar": "ready" if diar else "off",
                    "mt": "ready" if mt else "off"
                })
            except Exception:
                pass
        except Exception as e:
            logger.bind(tag="ws.stream").exception(e)
            try:
                await _safe_send_json(ws, {
                    "type": "warn",
                    "message": "ASR初期化に失敗。録音のみ継続します(停止後にバッチ転記)。"
                })
            except Exception:
                pass

    # 起動直後の通知（ASRは裏で準備中）
    try:
        await _safe_send_json(ws, {
            "type": "warn",
            "message": "ASR初期化中。録音は開始しています。"
        })
    except Exception:
        pass
    import asyncio as _asyncio
    _asyncio.create_task(_init_models())

    final_status = "completed"
    try:
        idle = 0
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_bytes(), timeout=3.0)
                idle = 0
            except asyncio.TimeoutError:
                idle += 3
                logger.bind(tag="ws.stream").info(f"idle {idle}s: no audio received for event={event_id}")
                # クライアントへも通知
                try:
                    await _safe_send_json(ws, {"type": "stat", "idle": idle})
                except Exception:
                    pass
                continue
            _append_audio(data)
            # 生PCMを追記保存
            try:
                wav.writeframes(data)
                # 可能なら明示フラッシュ（実装依存）
                try:
                    wav._file.flush()  # type: ignore[attr-defined]
                except Exception:
                    pass
                bytes_written += len(data)
                chunks += 1
            except Exception:
                # 保存失敗は処理継続しつつログ
                logger.bind(tag="ws.stream").exception("failed to write wav chunk")
            # 受信ログ（1秒に1回程度）
            now = time.time()
            if now - last_log >= 1.0:
                try:
                    fsz = os.path.getsize(wav_path)
                except Exception:
                    fsz = -1
                logger.bind(tag="ws.stream").debug(
                    f"recv event={event_id} chunks={chunks} bytes={bytes_written} file={fsz}B elapsed={now - t_start:.1f}s"
                )
                # クライアントにも統計を送る（デバッグ用）
                await _safe_send_json(ws, {
                    "type": "stat",
                    "chunks": chunks,
                    "bytes": bytes_written,
                    "file": fsz,
                    "elapsed": round(now - t_start, 1),
                    "diar": "ready" if _is_diar_ready() else "off",
                    "speakers": sorted(seen_speakers),
                    "last_speaker": last_speaker,
                    "mt": "ready" if mt else "off",
                })
                last_log = now
            t0 = time.time()
            # data: PCM16 16k mono chunk（20ms前提）
            logger.bind(tag="ws.stream").trace(f"received audio chunk: {len(data)} bytes")
            if asr is not None:
                try:
                    partial = asr.accept_chunk(data)
                    payload = _serialize_partial(partial)
                    if payload:
                        await _safe_send_json(ws, payload)

                    final_segments: List[Tuple[float, float, str, Optional[bytes]]] = []
                    seg_from_partial = _as_final_segment(partial)
                    if seg_from_partial:
                        final_segments.append(seg_from_partial)

                    fin = asr.try_finalize()
                    seg_from_try = _as_final_segment(fin)
                    if seg_from_try:
                        final_segments.append(seg_from_try)

                    for s, e, text, seg_audio_bytes in final_segments:
                        key = _normalize_final_key(text)
                        if key and _is_recent_final_key(key):
                            logger.bind(tag="ws.stream").debug("skip duplicate final", text_preview=text[:30])
                            continue
                        seg_audio = seg_audio_bytes or _extract_audio_segment(s, e) or data
                        speaker_label: Optional[str] = None
                        if asr and hasattr(asr, "majority_speaker"):
                            try:
                                speaker_label = asr.majority_speaker(s, e)  # type: ignore[attr-defined]
                            except Exception:
                                speaker_label = None
                        if (not speaker_label) and diar:
                            speaker_label = diar.assign_speaker(seg_audio, (s, e))
                        spk = speaker_label or "S1"
                        t_mt = mt.maybe_translate(text) if mt else ""
                        await insert_segment(event_id, s, e, spk, text, t_mt, origin="live")
                        seen_speakers.add(spk)
                        last_speaker = spk
                        if _is_diar_ready():
                            await _safe_send_json(ws, {
                                "type": "stat",
                                "diar": "ready",
                                "speakers": sorted(seen_speakers),
                                "last_speaker": last_speaker,
                                "mt": "ready" if mt else "off"
                            })
                        if key:
                            _remember_final_key(key)
                        await emit_final(text, s, e, spk, t_mt or "")
                except Exception as e:
                    # ASR 系の例外は録音継続を優先し、ASRを無効化
                    logger.bind(tag="ws.stream").exception(f"ASR processing error: {e}")
                    asr = None
                    await _safe_send_json(ws, {
                        "type": "warn",
                        "message": "ASR処理を停止しました。録音のみ継続します。"
                    })
            else:
                logger.bind(tag="ws.stream").debug("ASR is None, skipping audio processing")
            # latency guard - no artificial delay (chunk cadence is driven by sender)
            _ = time.time() - t0
            await asyncio.sleep(0)

    except WebSocketDisconnect:
        final_status = "client_disconnect"
        logger.bind(tag="ws.stream").info("client disconnected")
    except RuntimeError as e:
        final_status = "runtime_error"
        msg = str(e)
        if "websocket is not connected" in msg.lower():
            logger.bind(tag="ws.stream").info("client closed websocket before accept/receive completed")
        else:
            logger.bind(tag="ws.stream").exception(e)
        await _safe_close_ws(ws, code=1011)
    except Exception as e:
        final_status = "error"
        logger.bind(tag="ws.stream").exception(e)
        await _safe_close_ws(ws, code=1011)
    finally:
        stop_evt.set()
        if keepalive_task:
            keepalive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await keepalive_task
        try:
            wav.close()
        except Exception:
            pass
        # 終了時点のファイルサイズも記録
        try:
            fsz = os.path.getsize(wav_path)
        except Exception:
            fsz = -1
        duration = time.time() - t_start
        logger.bind(tag="ws.stream").info(
            f"WS stop event={event_id} chunks={chunks} bytes={bytes_written} file={fsz}B duration={duration:.1f}s status={final_status}"
        )
        _remember_stream_stat(event_id, chunks, bytes_written, duration, final_status)
