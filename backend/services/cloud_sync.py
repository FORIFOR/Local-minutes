from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from loguru import logger

from backend.local_config import settings as local_settings
from backend.store import db, minutes_repo


def _ts_to_iso(ts: Optional[int]) -> Optional[str]:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


async def _build_payload(event_id: str) -> Optional[Dict[str, Any]]:
    event = await db.get_event(event_id)
    if not event:
        return None
    user = None
    if event.get("user_id"):
        user = await db.get_user_by_id(int(event["user_id"]))
    minutes_text = await minutes_repo.get_text(event_id, event.get("user_id"))
    summary = await db.get_latest_summary(event_id, event.get("user_id"))
    payload: Dict[str, Any] = {
        "local_event_id": event_id,
        "title": event.get("title") or event_id,
        "lang": event.get("lang") or "ja",
        "started_at": _ts_to_iso(event.get("start_ts")),
        "ended_at": _ts_to_iso(event.get("end_ts")),
        "summary": (summary or {}).get("text_md") or "",
        "full_transcript": minutes_text or "",
        "participants": event.get("participants_json") or "",
    }
    if local_settings.cloud_sync_attach_segments:
        payload["segments"] = await db.list_segments(event_id, event.get("user_id"))
    if user:
        payload["user"] = {
            "id": user["id"],
            "email": user.get("email"),
            "name": user.get("name"),
        }
    return payload


async def sync_event_to_cloud(event_id: str, *, reason: str = "manual") -> Optional[Dict[str, Any]]:
    if not local_settings.cloud_sync_enabled:
        logger.bind(tag="cloud.sync", event=event_id).info("cloud sync disabled; skip")
        return None
    if not local_settings.cloud_api_base or not local_settings.cloud_api_token:
        logger.bind(tag="cloud.sync", event=event_id).warning("cloud sync missing API base or token; skip")
        return None

    payload = await _build_payload(event_id)
    if not payload:
        logger.bind(tag="cloud.sync", event=event_id).warning("cloud sync skipped (event not found)")
        return None
    payload["reason"] = reason

    url = local_settings.cloud_api_base.rstrip("/") + "/api/meetings"
    headers = {
        "Authorization": f"Bearer {local_settings.cloud_api_token}",
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(local_settings.cloud_sync_timeout_sec, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        logger.bind(tag="cloud.sync", event=event_id).info("cloud sync success", response=data)
        return data


def sync_event_to_cloud_blocking(event_id: str, *, reason: str = "auto") -> Optional[Dict[str, Any]]:
    if not local_settings.cloud_sync_enabled:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(sync_event_to_cloud(event_id, reason=reason))
    else:
        return loop.create_task(sync_event_to_cloud(event_id, reason=reason))
