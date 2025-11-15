import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
from loguru import logger
from zoneinfo import ZoneInfo

from backend.store import db

GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary") or "primary"
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
CALENDAR_TIMEZONE = os.getenv("GOOGLE_CALENDAR_TIMEZONE", "Asia/Tokyo") or "UTC"
try:
    CALENDAR_TZINFO = ZoneInfo(CALENDAR_TIMEZONE)
except Exception:
    CALENDAR_TIMEZONE = "UTC"
    CALENDAR_TZINFO = ZoneInfo("UTC")


class GoogleCalendarError(RuntimeError):
    """Raised when Google Calendar sync fails."""


async def _ensure_google_account(user_id: int) -> Dict[str, Any]:
    user = await db.get_user_by_id(user_id)
    if not user or not user.get("google_id"):
        raise GoogleCalendarError("Googleアカウントが連携されていません")
    return user


async def _refresh_access_token(user: Dict[str, Any]) -> str:
    refresh_token = user.get("google_refresh_token")
    if not refresh_token:
        raise GoogleCalendarError("Googleの更新トークンがありません。もう一度ログインしてください")
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise GoogleCalendarError("GOOGLE_CLIENT_ID/SECRET が設定されていません")
    data = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(GOOGLE_TOKEN_ENDPOINT, data=data)
    if resp.status_code >= 400:
        logger.bind(tag="google.sync").warning("refresh token failed", payload=resp.text)
        raise GoogleCalendarError("Googleトークンの更新に失敗しました")
    payload = resp.json()
    access_token = payload.get("access_token")
    if not access_token:
        raise GoogleCalendarError("Googleトークンの形式が不正です")
    expires_in = int(payload.get("expires_in", 3600))
    expiry = int(time.time() + expires_in)
    await db.update_google_credentials(
        user_id=int(user["id"]),
        google_id=user["google_id"],
        access_token=access_token,
        refresh_token=payload.get("refresh_token"),
        token_expiry=expiry,
        scope=payload.get("scope"),
    )
    user["google_access_token"] = access_token
    user["google_token_expiry"] = expiry
    if payload.get("refresh_token"):
        user["google_refresh_token"] = payload["refresh_token"]
    return access_token


async def _ensure_access_token(user: Dict[str, Any]) -> str:
    token = user.get("google_access_token")
    expiry = user.get("google_token_expiry")
    if token and isinstance(expiry, int) and expiry - 120 > int(time.time()):
        return token
    if token and expiry is None:
        return token
    return await _refresh_access_token(user)


async def _calendar_request(method: str, path: str, token: str, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = f"{GOOGLE_CALENDAR_BASE}{path}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.request(method, url, headers=headers, json=json_body)
    if resp.status_code >= 400:
        logger.bind(tag="google.sync").warning("calendar API error", status=resp.status_code, body=resp.text)
        raise GoogleCalendarError("GoogleカレンダーAPI呼び出しに失敗しました")
    if resp.status_code == 204 or not resp.content:
        return {}
    return resp.json()


def _ts_to_local_iso(ts: int) -> str:
    dt = datetime.fromtimestamp(max(0, ts), CALENDAR_TZINFO)
    return dt.isoformat(timespec="seconds")


async def upsert_google_event_for_meeting(user_id: int, event: Dict[str, Any], minutes: str = "") -> Dict[str, Any]:
    user = await _ensure_google_account(user_id)
    token = await _ensure_access_token(user)
    start_ts = int(event.get("start_ts") or event.get("created_at") or time.time())
    end_ts = int(event.get("end_ts") or (start_ts + 3600))
    if end_ts <= start_ts:
        end_ts = start_ts + 3600
    description = (minutes or "").strip() or (event.get("title") or "")
    if len(description) > 6000:
        description = description[:5990] + "..."
    body = {
        "summary": event.get("title") or "Local Minutes Meeting",
        "description": description or "Local Minutes",
        "start": {
            "dateTime": _ts_to_local_iso(start_ts),
            "timeZone": CALENDAR_TIMEZONE,
        },
        "end": {
            "dateTime": _ts_to_local_iso(end_ts),
            "timeZone": CALENDAR_TIMEZONE,
        },
    }
    existing = event.get("google_event_id")
    if existing:
        data = await _calendar_request(
            "PUT",
            f"/calendars/{GOOGLE_CALENDAR_ID}/events/{existing}",
            token,
            json_body=body,
        )
    else:
        data = await _calendar_request(
            "POST",
            f"/calendars/{GOOGLE_CALENDAR_ID}/events",
            token,
            json_body=body,
        )
    return data


async def delete_google_event(user_id: int, google_event_id: str) -> None:
    if not google_event_id:
        return
    user = await _ensure_google_account(user_id)
    token = await _ensure_access_token(user)
    try:
        await _calendar_request(
            "DELETE",
            f"/calendars/{GOOGLE_CALENDAR_ID}/events/{google_event_id}",
            token,
        )
    except GoogleCalendarError as exc:
        logger.bind(tag="google.sync").warning("failed to delete google event", error=str(exc))
        raise


async def ensure_google_ready(user_id: int) -> Dict[str, Any]:
    return await _ensure_google_account(user_id)
