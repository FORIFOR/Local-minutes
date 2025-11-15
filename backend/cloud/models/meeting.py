from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ..db import Base


class Meeting(Base):
    __tablename__ = "cloud_meetings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("cloud_users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=False)
    summary = Column(Text, nullable=True)
    full_transcript = Column(Text, nullable=True)
    google_sync_enabled = Column(Boolean, default=False)
    google_event_id = Column(String(128), nullable=True)

    user = relationship("User", back_populates="meetings")
