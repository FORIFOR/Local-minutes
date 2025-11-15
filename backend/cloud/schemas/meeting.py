from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class MeetingBase(BaseModel):
    title: str = Field(..., max_length=200)
    started_at: datetime
    ended_at: datetime
    summary: Optional[str] = None
    full_transcript: Optional[str] = None
    google_sync_enabled: bool = False


class MeetingCreate(MeetingBase):
    pass


class MeetingRead(MeetingBase):
    id: int
    google_event_id: Optional[str] = None

    class Config:
        from_attributes = True
