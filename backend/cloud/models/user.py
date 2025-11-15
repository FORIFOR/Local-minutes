from __future__ import annotations

from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import relationship

from ..db import Base


class User(Base):
    __tablename__ = "cloud_users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    google_id = Column(String(255), unique=True, nullable=True, index=True)
    google_access_token = Column(Text, nullable=True)
    google_refresh_token = Column(Text, nullable=True)
    google_token_expiry = Column(String(64), nullable=True)
    google_scope = Column(Text, nullable=True)

    meetings = relationship("Meeting", back_populates="user", cascade="all, delete-orphan")
