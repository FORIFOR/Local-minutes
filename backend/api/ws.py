import asyncio
import os
import json
import time
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from backend.store.db import validate_ws_token, insert_segment
from backend.store.files import artifact_path_for_event
from backend.asr.stream_jp import RealtimeASR
from backend.diar.online_cluster import OnlineDiarizer
from backend.nlp.translate_ct2 import Translator


ws_router = APIRouter()


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

    # モデル初期化はバックグラウンドで実施（録音受信をブロックしない）
    asr = None
    diar = None
    mt = None

    async def _init_models():
        nonlocal asr, diar, mt
        try:
            logger.bind(tag="ws.stream").info("initializing ASR/diar/MT models in background")
            live_asr = os.getenv("M4_ASR_LIVE", "1").strip().lower() not in ("0", "off", "false")
            if live_asr:
                asr = RealtimeASR()
            else:
                asr = None
                logger.bind(tag="ws.stream").info("ASR live disabled via env (M4_ASR_LIVE=off)")
            diar = OnlineDiarizer()
            mt = Translator()
            logger.bind(tag="ws.stream").info("models ready: ASR/diar/MT initialized")
            try:
                if asr is not None:
                    await ws.send_text(json.dumps({
                        "type": "warn",
                        "message": "ASR初期化完了。以降はライブ転記が有効です。"
                    }))
                else:
                    await ws.send_text(json.dumps({
                        "type": "warn",
                        "message": "ASRは無効化されています（録音のみ）。"
                    }))
            except Exception:
                pass
        except Exception as e:
            logger.bind(tag="ws.stream").exception(e)
            try:
                await ws.send_text(json.dumps({
                    "type": "warn",
                    "message": "ASR初期化に失敗。録音のみ継続します(停止後にバッチ転記)。"
                }))
            except Exception:
                pass

    # 起動直後の通知（ASRは裏で準備中）
    try:
        await ws.send_text(json.dumps({
            "type": "warn",
            "message": "ASR初期化中。録音は開始しています。"
        }))
    except Exception:
        pass
    import asyncio as _asyncio
    _asyncio.create_task(_init_models())

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
                    await ws.send_text(json.dumps({"type":"stat","idle": idle}))
                except Exception:
                    pass
                continue
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
                logger.bind(tag="ws.stream").info(
                    f"recv event={event_id} chunks={chunks} bytes={bytes_written} file={fsz}B elapsed={now - t_start:.1f}s"
                )
                # クライアントにも統計を送る（デバッグ用）
                try:
                    await ws.send_text(json.dumps({
                        "type": "stat",
                        "chunks": chunks,
                        "bytes": bytes_written,
                        "file": fsz,
                        "elapsed": round(now - t_start, 1)
                    }))
                except Exception:
                    pass
                last_log = now
            t0 = time.time()
            # data: PCM16 16k mono 1.0s
            logger.bind(tag="ws.stream").debug(f"received audio chunk: {len(data)} bytes")
            if asr is not None:
                try:
                    logger.bind(tag="ws.stream").debug(f"calling asr.accept_chunk with {len(data)} bytes")
                    partial = asr.accept_chunk(data)
                    logger.bind(tag="ws.stream").debug(f"asr.accept_chunk returned: {repr(partial)}")
                    if partial:
                        logger.bind(tag="ws.stream").info(f"partial result: {partial}")
                        await ws.send_text(json.dumps({"type": "partial", "text": partial}))

                    logger.bind(tag="ws.stream").debug("calling asr.try_finalize")
                    fin = asr.try_finalize()
                    logger.bind(tag="ws.stream").debug(f"asr.try_finalize returned: {repr(fin)}")
                    if fin:
                        s, e, text = fin
                        logger.bind(tag="ws.stream").info(f"final result: {text} [{s:.2f}-{e:.2f}s]")
                        spk = diar.assign_speaker(data, (s, e)) if diar else "S1"
                        t_mt = mt.maybe_translate(text) if mt else ""
                        await insert_segment(event_id, s, e, spk, text, t_mt, origin="live")
                        await ws.send_text(
                            json.dumps(
                                {
                                    "type": "final",
                                    "text": text,
                                    "range": [s, e],
                                    "speaker": spk,
                                    "mt": t_mt or "",
                                }
                            )
                        )
                except Exception as e:
                    # ASR 系の例外は録音継続を優先し、ASRを無効化
                    logger.bind(tag="ws.stream").exception(f"ASR processing error: {e}")
                    asr = None
                    try:
                        await ws.send_text(json.dumps({
                            "type": "warn",
                            "message": "ASR処理を停止しました。録音のみ継続します。"
                        }))
                    except Exception:
                        pass
            else:
                logger.bind(tag="ws.stream").debug("ASR is None, skipping audio processing")
            # latency guard
            dt = time.time() - t0
            await asyncio.sleep(max(0.0, 0.8 - dt))

    except WebSocketDisconnect:
        logger.bind(tag="ws.stream").info("client disconnected")
    except Exception as e:
        logger.bind(tag="ws.stream").exception(e)
        await ws.close()
    finally:
        try:
            wav.close()
        except Exception:
            pass
        # 終了時点のファイルサイズも記録
        try:
            fsz = os.path.getsize(wav_path)
        except Exception:
            fsz = -1
        logger.bind(tag="ws.stream").info(
            f"WS stop event={event_id} chunks={chunks} bytes={bytes_written} file={fsz}B duration={time.time() - t_start:.1f}s"
        )
