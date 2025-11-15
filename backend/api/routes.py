import json
import asyncio
import os
import time
import uuid
from pathlib import Path
from threading import Thread
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from loguru import logger

from backend.store import db as store, minutes_repo
from backend.store.db import touch_updated
from backend.store.files import artifact_path_for_event
from backend.store.files import artifact_dir
from backend.util.formatters import export_srt, export_vtt, export_rttm, export_ics
from backend.api.deps import AuthUser, get_current_user
from backend.diar.fluidaudio import (
    attach_speakers_to_whisper,
    build_minutes_text,
    run_fluidaudio,
)
from backend.services.cloud_sync import sync_event_to_cloud_blocking

router = APIRouter()
STOPPING_EVENTS: Set[str] = set()


def _should_run_summary() -> bool:
    if os.getenv("M4_BATCH_SUMMARY", "off").strip().lower() in ("0", "off", "false"):
        logger.bind(tag="job.batch").info("skip summary batch (M4_BATCH_SUMMARY=off)")
        return False
    provider = os.getenv("M4_LLM_PROVIDER", "").strip().lower()
    if provider in ("ollama", "openai"):
        base = os.getenv("M4_OLLAMA_BASE", "http://127.0.0.1:11434")
        try:
            import httpx

            r = httpx.get(base.rstrip("/") + "/v1/models", timeout=3.0)
            if r.status_code >= 500:
                logger.bind(tag="job.batch").warning(f"Ollama API {r.status_code}")
                return False
            return True
        except Exception as exc:
            logger.bind(tag="job.batch").warning(f"Ollama unreachable: {exc}")
            return False
    llm_model = os.getenv("M4_LLM_MODEL", "").strip()
    llm_bin = os.getenv("M4_LLM_BIN", "").strip()
    import shutil

    resolved = shutil.which(llm_bin or "llama-cli") or shutil.which("llama")
    if not (resolved and llm_model and os.path.exists(llm_model)):
        logger.bind(tag="job.batch").warning("Summary skipped: llama.cpp未構成")
        return False
    return True


def _run_post_pipeline(event_id: str, should_summary: bool) -> None:
    logger.bind(tag="job.batch").info(f"post pipeline start for {event_id}")
    try:
        batch_flag = os.getenv("M4_BATCH_WHISPER", "off").strip().lower()
        logger.bind(tag="job.batch").info(f"CONF batch_whisper={batch_flag}")
        if batch_flag in ("1", "true", "on", "yes"):
            from backend.asr.batch_whisper import run_batch_retranscribe

            try:
                run_batch_retranscribe(event_id)
            except Exception as exc:
                logger.bind(tag="job.batch").warning("whisper batch failed", error=repr(exc))
        else:
            logger.bind(tag="job.batch").info("skip whisper batch by env")

        if os.getenv("M4_BATCH_TRANSLATE", "off").strip().lower() not in ("0", "off", "false"):
            from backend.nlp.translate_ct2 import retranslate_event

            retranslate_event(event_id)
        else:
            logger.bind(tag="job.batch").info("skip translate batch (M4_BATCH_TRANSLATE=off)")

        diar_batch_enabled = os.getenv("M4_ENABLE_DIAR_BATCH", "off").strip().lower() not in ("0", "off", "false")
        diar_engine = os.getenv("M4_DIAR_ENGINE", "").strip().lower()
        if diar_batch_enabled and diar_engine == "fluidaudio":
            try:
                _run_fluidaudio_pipeline(event_id)
            except Exception as exc:
                logger.bind(tag="diar.batch").exception(exc)

        if should_summary:
            from backend.nlp.summarize_llama import finalize_summary_for_event

            finalize_summary_for_event(event_id)
        touch_updated(event_id)
        try:
            sync_event_to_cloud_blocking(event_id, reason="post-pipeline")
        except Exception as exc:
            logger.bind(tag="cloud.sync", event=event_id).warning("cloud sync failed", error=repr(exc))
    except Exception as exc:
        logger.bind(tag="job.batch").exception(exc)
    logger.bind(tag="job.batch").info(f"post pipeline done for {event_id}")


def _launch_post_pipeline(event_id: str) -> None:
    Thread(target=_run_post_pipeline, args=(event_id, _should_run_summary()), daemon=True).start()


def _run_fluidaudio_pipeline(event_id: str) -> None:
    wav_path = Path(artifact_path_for_event(event_id, "record.wav"))
    if not wav_path.exists():
        logger.bind(tag="diar.batch").warning("fluidaudio skipped (wav missing)", event=event_id)
        return
    out_json = Path(artifact_path_for_event(event_id, "diar.json"))
    bin_path = os.getenv("M4_FLUIDAUDIO_BIN", "fluidaudio")
    mode = os.getenv("M4_FLUIDAUDIO_MODE", "offline")
    threshold = float(os.getenv("M4_FLUIDAUDIO_THRESHOLD", "0.60"))
    diar = run_fluidaudio(wav_path, out_json, bin_path=bin_path, threshold=threshold, mode=mode)

    whisper_path = Path(artifact_path_for_event(event_id, "whisper.json"))
    if not whisper_path.exists():
        logger.bind(tag="diar.batch").warning("whisper.json missing; speaker attach skipped", event=event_id)
        return

    whisper_data = json.loads(whisper_path.read_text(encoding="utf-8"))
    enriched = attach_speakers_to_whisper(whisper_data, diar)
    spk_path = Path(artifact_path_for_event(event_id, "whisper.spk.json"))
    spk_path.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.bind(tag="diar.batch").info("whisper speaker map saved", path=str(spk_path))

    autofill = os.getenv("M4_AUTOFILL_MINUTES", "off").strip().lower() not in ("0", "off", "false", "")
    if autofill:
        minutes_text = build_minutes_text(enriched.get("segments", []))
        if minutes_text:
            asyncio.run(minutes_repo.upsert(event_id, body=minutes_text))
            logger.bind(tag="diar.batch").info("minutes autofilled from fluidaudio result", event=event_id)


async def _resolve_event_id(requested_id: str, user: AuthUser) -> Optional[str]:
    """Resolve a valid event id for stop requests, supporting the _latest alias."""
    candidate = (requested_id or "").strip()
    if candidate and candidate != "_latest":
        ev = await store.get_event(candidate, user.id)
        if ev:
            return candidate
    try:
        latest_user = await store.list_events_range(user.id, limit=1)
    except TypeError:
        latest_user = []
    if latest_user:
        return latest_user[0]["id"]
    try:
        latest_global = await store.list_events(limit=1)
    except AttributeError:
        latest_global = []
    if latest_global:
        return latest_global[0]["id"]
    return None


class EventCreate(BaseModel):
    title: str
    start_ts: int
    end_ts: Optional[int] = None
    lang: str = Field(default="ja")
    translate_to: Optional[str] = Field(default=None)

class EventUpdate(BaseModel):
    title: Optional[str] = None
    start_ts: Optional[int] = None
    end_ts: Optional[int] = None
    lang: Optional[str] = None
    translate_to: Optional[str] = None
    participants_json: Optional[str] = None


@router.post("/api/events")
async def create_event(body: EventCreate, user: AuthUser = Depends(get_current_user)):
    eid = str(uuid.uuid4())
    await store.create_event(
        user.id,
        eid,
        title=body.title,
        start_ts=body.start_ts,
        end_ts=body.end_ts or 0,
        lang=body.lang,
        translate_to=body.translate_to or "",
    )
    logger.bind(tag="api.events").info(f"created event {eid} by user {user.id}")
    return {"id": eid}


@router.put("/api/events/{event_id}")
async def update_event(event_id: str, body: EventUpdate, user: AuthUser = Depends(get_current_user)):
    ok = await store.update_event_fields(
        event_id,
        user_id=user.id,
        title=body.title,
        start_ts=body.start_ts,
        end_ts=body.end_ts,
        lang=body.lang,
        translate_to=body.translate_to,
        participants_json=body.participants_json,
    )
    if not ok:
        raise HTTPException(404, "event not found")
    return {"ok": True}


class ActionCreate(BaseModel):
    side: str
    assignee: str
    due_ts: int
    content: str


class ActionUpdate(BaseModel):
    side: Optional[str] = None
    assignee: Optional[str] = None
    due_ts: Optional[int] = None
    content: Optional[str] = None
    done: Optional[int] = None


@router.get("/api/events/{event_id}/actions")
async def list_actions(event_id: str, user: AuthUser = Depends(get_current_user)):
    ev = await store.get_event(event_id, user.id)
    if not ev:
        raise HTTPException(404, "event not found")
    items = await store.list_actions(event_id, user.id)
    return {"items": items}


@router.post("/api/events/{event_id}/actions")
async def create_action_api(event_id: str, body: ActionCreate, user: AuthUser = Depends(get_current_user)):
    aid = await store.create_action(event_id, body.side, body.assignee, body.due_ts, body.content, user_id=user.id)
    if not aid:
        raise HTTPException(404, "event not found")
    return {"id": aid}


@router.put("/api/events/{event_id}/actions/{action_id}")
async def update_action_api(event_id: str, action_id: int, body: ActionUpdate, user: AuthUser = Depends(get_current_user)):
    ok = await store.update_action(
        event_id,
        action_id,
        user_id=user.id,
        side=body.side,
        assignee=body.assignee,
        due_ts=body.due_ts,
        content=body.content,
        done=body.done,
    )
    if not ok:
        raise HTTPException(404, "action not found")
    return {"ok": True}


@router.delete("/api/events/{event_id}/actions/{action_id}")
async def delete_action_api(event_id: str, action_id: int, user: AuthUser = Depends(get_current_user)):
    ok = await store.delete_action(event_id, action_id, user_id=user.id)
    if not ok:
        raise HTTPException(404, "action not found")
    return {"ok": True}


@router.post("/api/events/{event_id}/start")
async def start_event(event_id: str, user: AuthUser = Depends(get_current_user)):
    token = str(uuid.uuid4())
    ok = await store.set_event_ws_token(event_id, token, user_id=user.id)
    if not ok:
        raise HTTPException(404, "event not found")
    return {"token": token}


@router.post("/api/events/{event_id}/stop")
async def stop_event(event_id: str, user: AuthUser = Depends(get_current_user)):
    resolved_event_id = await _resolve_event_id(event_id, user)
    if not resolved_event_id:
        logger.bind(tag="api.stop", requested=event_id, user=user.id).info("stop ignored: no accessible event")
        return {"ok": True, "id": None}
    logger.bind(tag="api.stop", requested=event_id, resolved=resolved_event_id, user=user.id).info("stop request")
    logger.info("stop request", req_id=event_id, resolved_id=resolved_event_id)
    stop_key = f"{user.id}:{resolved_event_id}"
    if stop_key in STOPPING_EVENTS:
        logger.bind(tag="api.stop", event=resolved_event_id).info("stop ignored (already stopping)")
        return {"ok": True, "id": resolved_event_id}
    STOPPING_EVENTS.add(stop_key)
    try:
        ev = await store.get_event(resolved_event_id, user.id)
        if not ev:
            logger.bind(tag="api.stop", event=resolved_event_id).warning("stop requested but event inaccessible")
            return {"ok": True, "id": resolved_event_id}
        _launch_post_pipeline(resolved_event_id)
        return {"ok": True, "id": resolved_event_id}
    finally:
        STOPPING_EVENTS.discard(stop_key)


@router.post("/api/events/_latest/stop")
async def stop_latest_event(user: AuthUser = Depends(get_current_user)):
    return await stop_event("_latest", user)


@router.get("/api/events/{event_id}/summary/stream")
async def stream_summary(event_id: str, user: AuthUser = Depends(get_current_user)):
    """要約のSSEストリーム。段階要約の途中結果と最終結果を順次送る。
    data: {type:'partial'|'final', text: str}
    """
    from starlette.responses import StreamingResponse
    import asyncio
    from threading import Thread
    from backend.nlp.summarize_llama import summarize_event_stream

    if not await store.get_event(event_id, user.id):
        raise HTTPException(404, "event not found")

    seg_preview = await store.list_segments(event_id, user.id)
    if not seg_preview:
        return JSONResponse({"message": "ライブ字幕がありません。録音を行ってから再度お試しください。"}, status_code=200)

    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    stop = False
    loop = asyncio.get_event_loop()

    def emit(msg: str):
        try:
            # put_nowait で落とすこともあるが、SSEは最新が重要なので古いキューを捨てる戦略でもよい
            # ここではブロックしない挙動を維持
            loop.call_soon_threadsafe(queue.put_nowait, msg)
        except Exception:
            pass

    def _job():
        try:
            summarize_event_stream(event_id, emit)
        except Exception as e:
            from loguru import logger
            logger.bind(tag="api.sse").exception(e)
        finally:
            try:
                # final通知がなかった場合でもSSEを閉じるため空データを送る
                loop.call_soon_threadsafe(queue.put_nowait, "[DONE]")
            except Exception:
                pass

    Thread(target=_job, daemon=True).start()

    async def gen():
        # ヘッダ: text/event-stream は StreamingResponse で指定する
        # 初期メッセージ(任意)
        yield b":ok\n\n"
        while True:
            try:
                item = await queue.get()
            except asyncio.CancelledError:
                break
            if item == "[DONE]":
                break
            data = f"data: {item}\n\n".encode("utf-8")
            yield data
        # 終端
        yield b"event: end\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


class QARequest(BaseModel):
    q: str


@router.post("/api/events/{event_id}/qa")
async def qa_event(event_id: str, body: QARequest, user: AuthUser = Depends(get_current_user)):
    """要約と発話をコンテキストにした簡易QA。Ollama優先。"""
    from backend.nlp.summarize_llama import run_chat_once
    ev = await store.get_event(event_id, user.id)
    if not ev:
        raise HTTPException(404, "event not found")
    segs = await store.list_segments(event_id, user.id)
    summ = await store.get_latest_summary(event_id, user.id)
    context = []
    if summ and summ.get("text_md"):
        context.append("## 要約\n" + (summ.get("text_md") or ""))
    # 直近の発話を少量だけ付与（長すぎると重い）
    last = "\n".join((s.get("text_ja") or s.get("text") or "") for s in segs[-50:])
    if last.strip():
        context.append("## 直近の発話\n" + last)
    prompt = (
        "以下の会議コンテキストに基づき、ユーザの質問に日本語で簡潔かつ正確に回答してください。\n" +
        "必要なら箇条書きを使い、推測は避け事実ベースで答えてください。\n\n" +
        "".join(context) +
        "\n\n## 質問\n" + body.q
    )
    ans = run_chat_once(prompt) or ""
    return {"answer": ans}


@router.post("/api/events/{event_id}/postprocess")
async def postprocess_event(event_id: str, user: AuthUser = Depends(get_current_user)):
    # 停止ボタンとは独立して、明示的に事後処理だけを起動
    from threading import Thread
    from backend.store.db import touch_updated

    ev = await store.get_event(event_id, user.id)
    if not ev:
        raise HTTPException(404, "event not found")

    def _job():
        logger.bind(tag="job.post").info(f"post pipeline start for {event_id}")
        try:
            if os.getenv("M4_BATCH_WHISPER", "on").strip().lower() not in ("0","off","false"):
                from backend.asr.batch_whisper import run_batch_retranscribe
                try:
                    run_batch_retranscribe(event_id)
                except Exception as exc:
                    logger.bind(tag="job.post").warning("whisper batch failed", error=repr(exc))
            else:
                logger.bind(tag="job.post").info("skip whisper batch (M4_BATCH_WHISPER=off)")

            if os.getenv("M4_BATCH_TRANSLATE", "off").strip().lower() not in ("0","off","false"):
                from backend.nlp.translate_ct2 import retranslate_event
                retranslate_event(event_id)
            else:
                logger.bind(tag="job.post").info("skip translate batch (M4_BATCH_TRANSLATE=off)")

            if os.getenv("M4_BATCH_SUMMARY", "off").strip().lower() not in ("0","off","false"):
                from backend.nlp.summarize_llama import finalize_summary_for_event
                finalize_summary_for_event(event_id)
            else:
                logger.bind(tag="job.post").info("skip summary batch (M4_BATCH_SUMMARY=off)")
            touch_updated(event_id)
        except Exception as e:
            logger.bind(tag="job.post").exception(e)
        logger.bind(tag="job.post").info(f"post pipeline done for {event_id}")

    Thread(target=_job, daemon=True).start()
    return {"ok": True}


@router.get("/api/events/search")
async def search_events(q: str = "", limit: int = 20, user: AuthUser = Depends(get_current_user)):
    rows = await store.search_events_by_title(user.id, q, limit=min(max(limit, 1), 100))
    return {"items": rows}


@router.get("/api/events/{event_id}")
async def get_event(event_id: str, user: AuthUser = Depends(get_current_user)):
    ev = await store.get_event(event_id, user.id)
    if not ev:
        raise HTTPException(404, "event not found")
    ev.pop("user_id", None)
    segs = await store.list_segments(event_id, user.id)
    summary = await store.get_latest_summary(event_id, user.id)
    return {"event": ev, "segments": segs, "summary": summary}


@router.get("/api/events/{event_id}/minutes")
async def get_minutes_api(event_id: str, user: AuthUser = Depends(get_current_user)):
    try:
        md = await store.get_minutes(event_id, user.id)
    except PermissionError:
        raise HTTPException(404, "event not found")
    return {"md": md}


class MinutesUpdate(BaseModel):
    md: str = ""


@router.put("/api/events/{event_id}/minutes")
async def set_minutes_api(event_id: str, body: MinutesUpdate, user: AuthUser = Depends(get_current_user)):
    ok = await store.set_minutes(event_id, body.md or "", user.id)
    if not ok:
        raise HTTPException(404, "event not found")
    return {"ok": True}


@router.get("/api/search")
async def search(q: str, user: AuthUser = Depends(get_current_user)):
    rows = await store.fts_search(user.id, q)
    return {"items": rows}


@router.get("/api/events")
async def list_events(ts_from: Optional[int] = None, ts_to: Optional[int] = None, limit: int = 500, user: AuthUser = Depends(get_current_user)):
    """イベント一覧（カレンダー/管理用）。
    - ts_from/ts_to はUNIX秒。未指定時は最新順で最大limit件
    """
    rows = await store.list_events_range(user.id, ts_from, ts_to, limit)
    return {"items": rows}


@router.post("/api/events/{event_id}/translate")
async def change_translate(event_id: str, target: str, user: AuthUser = Depends(get_current_user)):
    """翻訳ターゲットを変更し、再翻訳をバックグラウンドで実行する。
    ASGIループ直下では asyncio.run を呼ばず、スレッドに逃がす。
    """
    ok = await store.set_translate_to(event_id, target, user.id)
    if not ok:
        raise HTTPException(404, "event not found")
    from threading import Thread
    from backend.nlp.translate_ct2 import retranslate_event

    def _job():
        try:
            retranslate_event(event_id)
        except Exception as e:
            from loguru import logger as _logger
            _logger.bind(tag="api.translate").exception(e)

    Thread(target=_job, daemon=True).start()
    return {"ok": True}


@router.post("/api/events/{event_id}/summarize")
async def summarize_event(event_id: str, user: AuthUser = Depends(get_current_user)):
    """イベント全文から要約を生成して保存する。
    - 非同期実行: ASGIイベントループ直下で asyncio.run を呼ばないため、バックグラウンドスレッドで実行。
    - 完了後に updated_at をタッチ。
    """
    ev = await store.get_event(event_id, user.id)
    if not ev:
        raise HTTPException(404, "event not found")
    try:
        minutes_md = await store.get_minutes(event_id, user.id)
    except PermissionError:
        raise HTTPException(404, "event not found")
    minutes_text = (minutes_md or "").strip()
    unique_ratio = (len(set(minutes_text)) / len(minutes_text)) if minutes_text else 0.0
    if len(minutes_text) < 20 or unique_ratio < 0.05:
        return {"ok": False, "message": "会議内容がありません。"}

    from threading import Thread
    from backend.nlp.summarize_llama import finalize_summary_for_event
    from backend.store.db import touch_updated

    def _job():
        try:
            finalize_summary_for_event(event_id)
            touch_updated(event_id)
        except Exception as e:
            logger.bind(tag="api.summarize").exception(e)

    Thread(target=_job, daemon=True).start()
    return {"ok": True}


@router.delete("/api/events/{event_id}")
async def delete_event(event_id: str, user: AuthUser = Depends(get_current_user)):
    # DBからイベントと関連データを削除し、アーティファクトも消去
    import shutil

    ok = await store.delete_event(event_id, user.id)
    if not ok:
        raise HTTPException(404, "event not found")
    d = os.path.join(artifact_dir(), event_id)
    shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


@router.get("/download.srt")
async def download_srt(id: str, user: AuthUser = Depends(get_current_user)):
    segs = await store.list_segments(id, user.id)
    content = export_srt(segs)
    return {"content": content}


@router.get("/download.vtt")
async def download_vtt(id: str, user: AuthUser = Depends(get_current_user)):
    segs = await store.list_segments(id, user.id)
    content = export_vtt(segs)
    return {"content": content}


@router.get("/download.rttm")
async def download_rttm(id: str, user: AuthUser = Depends(get_current_user)):
    segs = await store.list_segments(id, user.id)
    content = export_rttm(id, segs)
    return {"content": content}


@router.get("/download.ics")
async def download_ics(id: str, user: AuthUser = Depends(get_current_user)):
    ev = await store.get_event(id, user.id)
    if not ev:
        raise HTTPException(404, "event not found")
    content = export_ics(ev)
    return {"content": content}


@router.get("/api/events/{event_id}/artifacts")
async def list_artifacts(event_id: str, user: AuthUser = Depends(get_current_user)):
    import os
    import time

    if not await store.get_event(event_id, user.id):
        raise HTTPException(404, "event not found")
    d = os.path.join(artifact_dir(), event_id)
    items = []
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                st = os.stat(p)
                items.append({
                    "name": name,
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "url": f"/api/events/{event_id}/artifacts/{name}",
                })
    try:
        total = sum(i.get("size", 0) for i in items)
        from loguru import logger
        logger.bind(tag="api.artifacts").info(f"list event={event_id} count={len(items)} total={total}B")
    except Exception:
        pass
    return {"items": items}


@router.get("/api/events/{event_id}/artifacts/{name}")
async def get_artifact(event_id: str, name: str, user: AuthUser = Depends(get_current_user)):
    import os
    if not await store.get_event(event_id, user.id):
        raise HTTPException(404, "event not found")
    # パストラバーサル防止: 絶対パスで比較
    base = os.path.abspath(os.path.join(artifact_dir(), event_id))
    p = os.path.abspath(os.path.normpath(os.path.join(base, name)))
    if not p.startswith(base + os.sep) and p != base:
        raise HTTPException(400, "invalid path")
    if not os.path.isfile(p):
        raise HTTPException(404, "artifact not found")
    try:
        st = os.stat(p)
        from loguru import logger
        logger.bind(tag="api.artifacts").info(f"get event={event_id} name={name} size={st.st_size}B")
    except Exception:
        pass
    return FileResponse(p)


# 暫定フォールバック: クライアント側でWAV生成してHTTPアップロード（最小範囲）
# 使用箇所: 録音の確認がブロックしている場合の退避路。WS保存が安定後に撤去予定。
@router.post("/api/events/{event_id}/upload")
async def upload_artifact(event_id: str, request: Request, user: AuthUser = Depends(get_current_user)):
    import os
    if not await store.get_event(event_id, user.id):
        raise HTTPException(404, "event not found")
    data = await request.body()
    base = os.path.abspath(os.path.join(artifact_dir(), event_id))
    os.makedirs(base, exist_ok=True)
    p = os.path.join(base, "record.wav")
    with open(p, "wb") as f:
        f.write(data)
    try:
        st = os.stat(p)
        from loguru import logger
        logger.bind(tag="api.artifacts").info(f"upload event={event_id} name=record.wav size={st.st_size}B")
    except Exception:
        pass
    return {"ok": True, "size": os.path.getsize(p)}
