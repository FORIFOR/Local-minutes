from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from backend.cloud.api import auth, auth_google, events, google_calendar, health, meetings
from backend.cloud.config import settings
from backend.cloud.db import init_db

app = FastAPI(title=settings.project_name)


@app.on_event("startup")
def startup() -> None:
    init_db()


origins = {
    settings.frontend_origin.rstrip("/"),
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://local-minutes-front.pages.dev",
}

allow_origin_regex = os.getenv("FRONTEND_ORIGIN_REGEX", "")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(origins),
    allow_origin_regex=allow_origin_regex or r"https://.*\.local-minutes-front\.pages\.dev",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)

app.include_router(auth.router, prefix="/api/auth")
app.include_router(auth_google.router, prefix="/api/auth")
app.include_router(meetings.router, prefix="/api/meetings")
app.include_router(google_calendar.router, prefix="/api/google")
app.include_router(events.router, prefix="/api")
app.include_router(health.router, prefix="/api/health")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
