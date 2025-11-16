from __future__ import annotations

import os
from typing import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from .config import settings

connect_args = {}
database_url = settings.database_url
sqlite_dir = settings.sqlite_dir

def _ensure_dir(path: str) -> str:
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except PermissionError:
        fallback = os.path.abspath("./cloud-data")
        os.makedirs(fallback, exist_ok=True)
        return fallback

if database_url.startswith("sqlite:///"):
    connect_args["check_same_thread"] = False
    base_dir = _ensure_dir(sqlite_dir)
    path = database_url.replace("sqlite:///", "", 1)
    if not path.startswith("/"):
        path = os.path.join(base_dir, path)
    database_url = f"sqlite:///{os.path.abspath(path)}"

engine = create_engine(database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db() -> None:
    from .models import meeting, user  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _apply_simple_migrations()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _apply_simple_migrations() -> None:
    """Ensure newer columns exist even if the table was created before."""
    inspector = inspect(engine)
    with engine.begin() as conn:
        if "cloud_users" in inspector.get_table_names():
            user_cols = {col["name"] for col in inspector.get_columns("cloud_users")}
            if "password_hash" not in user_cols:
                conn.execute(text("ALTER TABLE cloud_users ADD COLUMN password_hash VARCHAR(255)"))
        if "cloud_meetings" in inspector.get_table_names():
            meeting_cols = {col["name"] for col in inspector.get_columns("cloud_meetings")}
            if "full_transcript" not in meeting_cols:
                conn.execute(text("ALTER TABLE cloud_meetings ADD COLUMN full_transcript TEXT"))
