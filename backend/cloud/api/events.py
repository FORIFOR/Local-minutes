from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.cloud.db import get_db
from backend.cloud.models.meeting import Meeting
from backend.cloud.models.user import User
from backend.cloud.security import get_current_user

router = APIRouter()


def _serialize_meeting(meeting: Meeting) -> dict:
    start_ts = int(meeting.started_at.timestamp()) if meeting.started_at else None
    end_ts = int(meeting.ended_at.timestamp()) if meeting.ended_at else None
    return {
        "id": meeting.id,
        "title": meeting.title,
        "started_at": meeting.started_at.isoformat() if meeting.started_at else None,
        "ended_at": meeting.ended_at.isoformat() if meeting.ended_at else None,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "summary": meeting.summary,
        "full_transcript": meeting.full_transcript,
        "google_sync_enabled": meeting.google_sync_enabled,
    }


@router.get("/events")
def list_events(
    limit: int = 3,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[dict]:
    """Dashboardカードで使う最近のイベント一覧。"""
    limit = max(1, min(limit, 50))
    meetings = (
        db.query(Meeting)
        .filter(Meeting.user_id == user.id)
        .order_by(Meeting.started_at.desc())
        .limit(limit)
        .all()
    )
    return [_serialize_meeting(m) for m in meetings]


@router.get("/events/search")
def search_events(
    q: str = "*",
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[dict]:
    """タイトルがあいまい一致するイベント一覧。"""
    q = (q or "").strip()
    limit = max(1, min(limit, 50))
    query = db.query(Meeting).filter(Meeting.user_id == user.id)
    if q not in ("", "*"):
        safe = q.replace("%", "\\%").replace("_", "\\_")
        like = f"%{safe}%"
        query = query.filter(Meeting.title.ilike(like))
    meetings = query.order_by(Meeting.started_at.desc()).limit(limit).all()
    return [_serialize_meeting(m) for m in meetings]


@router.get("/events/{meeting_id}")
def read_event(
    meeting_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    meeting: Optional[Meeting] = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id, Meeting.user_id == user.id)
        .first()
    )
    if meeting is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return _serialize_meeting(meeting)
