from typing import Optional

from loguru import logger

from backend.store import db


async def get_text(event_id: str, user_id: Optional[int] = None) -> str:
    try:
        text = await db.get_minutes(event_id, user_id)
        return text or ""
    except PermissionError:
        logger.bind(tag="minutes.repo", event=event_id).warning("get_text permission denied", user_id=user_id)
        return ""


async def upsert(event_id: str, *, body: str, user_id: Optional[int] = None) -> bool:
    text = (body or "").strip()
    if not text:
        logger.bind(tag="minutes.repo", event=event_id).warning("reject empty update")
        return False

    existing = ""
    try:
        existing = await db.get_minutes(event_id, user_id)
    except PermissionError:
        logger.bind(tag="minutes.repo", event=event_id).warning("upsert permission denied", user_id=user_id)
        return False

    existing = existing or ""
    if existing and len(text) + 32 < len(existing):
        logger.bind(tag="minutes.repo", event=event_id).info(
            "reject shorter update",
            keep=len(existing),
            new=len(text),
        )
        return False

    updated = await db.set_minutes(event_id, text, user_id=user_id)
    if updated:
        logger.bind(tag="minutes.repo", event=event_id).info("minutes upserted", length=len(text))
    else:
        logger.bind(tag="minutes.repo", event=event_id).warning("minutes update failed")
    return updated
