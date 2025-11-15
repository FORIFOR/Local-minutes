from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.api.deps import AuthUser, get_current_user
from backend.services.google_calendar import (
    GoogleCalendarError,
    delete_google_event,
    upsert_google_event_for_meeting,
)
from backend.store import db

router = APIRouter(prefix="/api/events", tags=["google-sync"])


class GoogleSyncToggle(BaseModel):
    enabled: bool = Field(..., description="Googleカレンダー同期を有効にするか")


class MonthSyncRequest(BaseModel):
    year: int
    month: int = Field(..., ge=1, le=12)
    enabled: bool


async def _ensure_google_link(user: AuthUser) -> Dict[str, Any]:
    record = await db.get_user_by_id(user.id)
    if not record or not record.get("google_id"):
        raise HTTPException(status_code=400, detail="Googleアカウントと連携してください")
    if not record.get("google_refresh_token"):
        raise HTTPException(status_code=400, detail="Google連携に必要なトークンがありません。再ログインしてください")
    return record


async def _fetch_minutes(event_id: str, user_id: int) -> str:
    try:
        minutes = await db.get_minutes(event_id, user_id)
    except PermissionError:
        return ""
    return minutes or ""


@router.post("/{event_id}/google-sync")
async def toggle_event_google_sync(
    event_id: str,
    payload: GoogleSyncToggle,
    current_user: AuthUser = Depends(get_current_user),
):
    event = await db.get_event(event_id, current_user.id)
    if not event:
        raise HTTPException(status_code=404, detail="event not found")
    await _ensure_google_link(current_user)

    if payload.enabled:
        minutes = await _fetch_minutes(event_id, current_user.id)
        try:
            google_event = await upsert_google_event_for_meeting(current_user.id, event, minutes)
        except GoogleCalendarError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await db.set_event_google_sync(event_id, current_user.id, True, google_event.get("id"))
        event["google_sync_enabled"] = True
        event["google_event_id"] = google_event.get("id")
    else:
        if event.get("google_event_id"):
            try:
                await delete_google_event(current_user.id, event["google_event_id"])
            except GoogleCalendarError:
                # ignore deletion failures
                pass
        await db.set_event_google_sync(event_id, current_user.id, False, None)
        event["google_sync_enabled"] = False
        event["google_event_id"] = None

    return {
        "google_sync_enabled": event.get("google_sync_enabled", False),
        "google_event_id": event.get("google_event_id"),
    }


def _month_range(year: int, month: int) -> tuple[int, int]:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = start + relativedelta(months=1)
    return int(start.timestamp()), int(end.timestamp())


@router.post("/calendar/google-sync")
async def toggle_month_google_sync(
    body: MonthSyncRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    start_ts, end_ts = _month_range(body.year, body.month)
    events = await db.list_events_range(current_user.id, start_ts, end_ts)
    if not events:
        return {"processed": 0, "enabled": body.enabled}

    await _ensure_google_link(current_user)
    processed = 0

    for ev in events:
        event_id = ev["id"]
        if body.enabled:
            minutes = await _fetch_minutes(event_id, current_user.id)
            try:
                google_event = await upsert_google_event_for_meeting(current_user.id, ev, minutes)
            except GoogleCalendarError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            await db.set_event_google_sync(event_id, current_user.id, True, google_event.get("id"))
        else:
            if ev.get("google_event_id"):
                try:
                    await delete_google_event(current_user.id, ev["google_event_id"])
                except GoogleCalendarError:
                    pass
            await db.set_event_google_sync(event_id, current_user.id, False, None)
        processed += 1

    return {"processed": processed, "enabled": body.enabled}
