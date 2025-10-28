import os
import time
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from loguru import logger

from backend.store import db as store
from backend.store.files import artifact_path_for_event
from backend.store.files import artifact_dir
from backend.util.formatters import export_srt, export_vtt, export_rttm, export_ics

router = APIRouter()


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
async def create_event(body: EventCreate):
    eid = str(uuid.uuid4())
    await store.create_event(
        eid,
        title=body.title,
        start_ts=body.start_ts,
        end_ts=body.end_ts or 0,
        lang=body.lang,
        translate_to=body.translate_to or "",
    )
    logger.bind(tag="api.events").info(f"created event {eid}")
    return {"id": eid}


@router.put("/api/events/{event_id}")
async def update_event(event_id: str, body: EventUpdate):
    ok = await store.update_event_fields(
        event_id,
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
async def list_actions(event_id: str):
    items = await store.list_actions(event_id)
    return {"items": items}


@router.post("/api/events/{event_id}/actions")
async def create_action_api(event_id: str, body: ActionCreate):
    aid = await store.create_action(event_id, body.side, body.assignee, body.due_ts, body.content)
    return {"id": aid}


@router.put("/api/events/{event_id}/actions/{action_id}")
async def update_action_api(event_id: str, action_id: int, body: ActionUpdate):
    ok = await store.update_action(event_id, action_id, side=body.side, assignee=body.assignee, due_ts=body.due_ts, content=body.content, done=body.done)
    if not ok:
        raise HTTPException(404, "action not found")
    return {"ok": True}


@router.delete("/api/events/{event_id}/actions/{action_id}")
async def delete_action_api(event_id: str, action_id: int):
    ok = await store.delete_action(event_id, action_id)
    if not ok:
        raise HTTPException(404, "action not found")
    return {"ok": True}


@router.post("/api/events/{event_id}/start")
async def start_event(event_id: str):
    token = str(uuid.uuid4())
    await store.set_event_ws_token(event_id, token)
    return {"token": token}


@router.post("/api/events/{event_id}/stop")
async def stop_event(event_id: str):
    # 非同期の事後パイプラインは簡易にバックグラウンドスレッドで起動
    from threading import Thread
    from backend.store.db import touch_updated

    def _job():
        logger.bind(tag="job.batch").info(f"post pipeline start for {event_id}")
        try:
            # Whisper バッチ（envで制御）
            if os.getenv("M4_BATCH_WHISPER", "on").strip().lower() not in ("0","off","false"):
                from backend.asr.batch_whisper import run_batch_retranscribe
                run_batch_retranscribe(event_id)
            else:
                logger.bind(tag="job.batch").info("skip whisper batch (M4_BATCH_WHISPER=off)")

            # 翻訳（envで制御）
            if os.getenv("M4_BATCH_TRANSLATE", "off").strip().lower() not in ("0","off","false"):
                from backend.nlp.translate_ct2 import retranslate_event
                retranslate_event(event_id)
            else:
                logger.bind(tag="job.batch").info("skip translate batch (M4_BATCH_TRANSLATE=off)")

            # 要約（envで制御）
            if os.getenv("M4_BATCH_SUMMARY", "off").strip().lower() not in ("0","off","false"):
                from backend.nlp.summarize_llama import finalize_summary_for_event
                finalize_summary_for_event(event_id)
            else:
                logger.bind(tag="job.batch").info("skip summary batch (M4_BATCH_SUMMARY=off)")
            touch_updated(event_id)
        except Exception as e:
            logger.bind(tag="job.batch").exception(e)
        logger.bind(tag="job.batch").info(f"post pipeline done for {event_id}")

    Thread(target=_job, daemon=True).start()
    return {"ok": True}


@router.get("/api/events/{event_id}/summary/stream")
async def stream_summary(event_id: str):
    """要約のSSEストリーム。段階要約の途中結果と最終結果を順次送る。
    data: {type:'partial'|'final', text: str}
    """
    from starlette.responses import StreamingResponse
    import asyncio
    from threading import Thread
    from backend.nlp.summarize_llama import summarize_event_stream

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
async def qa_event(event_id: str, body: QARequest):
    """要約と発話をコンテキストにした簡易QA。Ollama優先。"""
    from backend.store import db as _db
    from backend.nlp.summarize_llama import run_chat_once
    ev = await _db.get_event(event_id)
    segs = await _db.list_segments(event_id)
    summ = await _db.get_latest_summary(event_id)
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
async def postprocess_event(event_id: str):
    # 停止ボタンとは独立して、明示的に事後処理だけを起動
    from threading import Thread
    from backend.store.db import touch_updated

    def _job():
        logger.bind(tag="job.post").info(f"post pipeline start for {event_id}")
        try:
            if os.getenv("M4_BATCH_WHISPER", "on").strip().lower() not in ("0","off","false"):
                from backend.asr.batch_whisper import run_batch_retranscribe
                run_batch_retranscribe(event_id)
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


@router.get("/api/events/{event_id}")
async def get_event(event_id: str):
    ev = await store.get_event(event_id)
    if not ev:
        raise HTTPException(404, "event not found")
    segs = await store.list_segments(event_id)
    summary = await store.get_latest_summary(event_id)
    return {"event": ev, "segments": segs, "summary": summary}


@router.get("/api/events/{event_id}/minutes")
async def get_minutes_api(event_id: str):
    md = await store.get_minutes(event_id)
    return {"md": md}


class MinutesUpdate(BaseModel):
    md: str = ""


@router.put("/api/events/{event_id}/minutes")
async def set_minutes_api(event_id: str, body: MinutesUpdate):
    await store.set_minutes(event_id, body.md or "")
    return {"ok": True}


@router.get("/api/search")
async def search(q: str):
    rows = await store.fts_search(q)
    return {"items": rows}


@router.get("/api/events")
async def list_events(ts_from: Optional[int] = None, ts_to: Optional[int] = None, limit: int = 500):
    """イベント一覧（カレンダー/管理用）。
    - ts_from/ts_to はUNIX秒。未指定時は最新順で最大limit件
    """
    rows = await store.list_events_range(ts_from, ts_to, limit)
    return {"items": rows}


@router.post("/api/events/{event_id}/translate")
async def change_translate(event_id: str, target: str):
    """翻訳ターゲットを変更し、再翻訳をバックグラウンドで実行する。
    ASGIループ直下では asyncio.run を呼ばず、スレッドに逃がす。
    """
    await store.set_translate_to(event_id, target)
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
async def summarize_event(event_id: str):
    """イベント全文から要約を生成して保存する。
    - 非同期実行: ASGIイベントループ直下で asyncio.run を呼ばないため、バックグラウンドスレッドで実行。
    - 完了後に updated_at をタッチ。
    """
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
async def delete_event(event_id: str):
    # DBからイベントと関連データを削除し、アーティファクトも消去
    import shutil, os
    await store.delete_event(event_id)
    d = os.path.join(artifact_dir(), event_id)
    shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


@router.get("/download.srt")
async def download_srt(id: str):
    segs = await store.list_segments(id)
    content = export_srt(segs)
    return {"content": content}


@router.get("/download.vtt")
async def download_vtt(id: str):
    segs = await store.list_segments(id)
    content = export_vtt(segs)
    return {"content": content}


@router.get("/download.rttm")
async def download_rttm(id: str):
    segs = await store.list_segments(id)
    content = export_rttm(id, segs)
    return {"content": content}


@router.get("/download.ics")
async def download_ics(id: str):
    ev = await store.get_event(id)
    if not ev:
        raise HTTPException(404, "event not found")
    content = export_ics(ev)
    return {"content": content}


@router.get("/api/events/{event_id}/artifacts")
async def list_artifacts(event_id: str):
    import os, time
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
async def get_artifact(event_id: str, name: str):
    import os
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
async def upload_artifact(event_id: str, request: Request):
    import os
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
