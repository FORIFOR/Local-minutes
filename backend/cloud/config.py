from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass
class Settings:
    project_name: str = os.getenv("CLOUD_PROJECT_NAME", "m4-meet cloud backend")
    session_secret: str = os.getenv("SESSION_SECRET", "change-me")
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./cloud.db")

    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_redirect_uri: str = os.getenv("GOOGLE_REDIRECT_URI", "")
    google_login_redirect_url: str = os.getenv("GOOGLE_LOGIN_REDIRECT_URL", "/")
    google_calendar_timezone: str = os.getenv("GOOGLE_CALENDAR_TIMEZONE", "Asia/Tokyo")
    google_calendar_id: str = os.getenv("GOOGLE_CALENDAR_ID", "primary")


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
