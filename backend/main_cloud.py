from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.cloud.api import auth_google, google_calendar, meetings
from backend.cloud.config import settings
from backend.cloud.db import init_db

app = FastAPI(title=settings.project_name)


@app.on_event("startup")
def startup() -> None:
    init_db()


origins = {settings.frontend_origin.rstrip("/")}
origins.add("http://localhost:5173")
origins.add("http://127.0.0.1:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_google.router)
app.include_router(meetings.router, prefix="/api/meetings")
app.include_router(google_calendar.router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
