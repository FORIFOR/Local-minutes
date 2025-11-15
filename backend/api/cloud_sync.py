from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.local_config import settings as local_settings
from backend.services.cloud_sync import sync_event_to_cloud
from backend.store import db

router = APIRouter()


@router.get("/config")
async def cloud_config():
    return {
        "enabled": local_settings.cloud_sync_enabled,
        "api_base": local_settings.cloud_api_base,
    }


@router.post("/events/{event_id}/sync")
async def sync_event(event_id: str):
    exists = await db.get_event(event_id)
    if not exists:
        raise HTTPException(status_code=404, detail="event not found")
    result = await sync_event_to_cloud(event_id, reason="manual-api")
    if isinstance(result, dict):
        return {"ok": True, "response": result}
    return {"ok": False, "response": None}
