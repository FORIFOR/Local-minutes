from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models.meeting import Meeting
from ..models.user import User
from ..security import get_current_user

router = APIRouter(prefix="/google", tags=["google"])


def _build_google_service(user: User):
    if not user.google_refresh_token:
        raise HTTPException(status_code=400, detail="Google account not linked")
    creds = Credentials(
        token=user.google_access_token,
        refresh_token=user.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=["https://www.googleapis.com/auth/calendar.events"],
    )
    return build("calendar", "v3", credentials=creds)


def _meeting_event_body(meeting: Meeting) -> dict:
    start = meeting.started_at.astimezone(timezone.utc).isoformat()
    end = meeting.ended_at.astimezone(timezone.utc).isoformat()
    return {
        "summary": meeting.title,
        "description": meeting.summary or "",
        "start": {"dateTime": start, "timeZone": settings.google_calendar_timezone},
        "end": {"dateTime": end, "timeZone": settings.google_calendar_timezone},
    }


@router.post("/meetings/{meeting_id}/sync")
def sync_meeting(
    meeting_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id, Meeting.user_id == user.id)
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    service = _build_google_service(user)

    body = _meeting_event_body(meeting)
    calendar_id = settings.google_calendar_id or "primary"
    if meeting.google_event_id:
        service.events().update(
            calendarId=calendar_id,
            eventId=meeting.google_event_id,
            body=body,
        ).execute()
    else:
        created = (
            service.events()
            .insert(calendarId=calendar_id, body=body)
            .execute()
        )
        meeting.google_event_id = created.get("id")
    meeting.google_sync_enabled = True
    db.commit()
    db.refresh(meeting)
    return {"google_event_id": meeting.google_event_id, "google_sync_enabled": meeting.google_sync_enabled}


@router.delete("/meetings/{meeting_id}/sync")
def unsync_meeting(
    meeting_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id, Meeting.user_id == user.id)
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.google_event_id:
        service = _build_google_service(user)
        calendar_id = settings.google_calendar_id or "primary"
        try:
            service.events().delete(calendarId=calendar_id, eventId=meeting.google_event_id).execute()
        except Exception:
            pass
    meeting.google_event_id = None
    meeting.google_sync_enabled = False
    db.commit()
    return {"google_sync_enabled": False}
