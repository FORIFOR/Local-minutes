import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Tuple

import aiosqlite

DB_PATH = os.path.join("backend", "data", "app.db")
SESSION_TTL_SECONDS = int(os.getenv("M4_SESSION_TTL", "1209600"))  # 14日

SCHEMA_SQL = r"""
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT,
    created_at INT NOT NULL,
    google_id TEXT UNIQUE,
    google_access_token TEXT,
    google_refresh_token TEXT,
    google_token_expiry INT,
    google_scope TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id INT NOT NULL,
    created_at INT NOT NULL,
    expires_at INT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    user_id INT,
    title TEXT,
    start_ts INT,
    end_ts INT,
    lang TEXT,
    translate_to TEXT,
    audio_path TEXT,
    audio_bytes INT,
    participants_json TEXT,
    google_sync_enabled INT NOT NULL DEFAULT 0,
    google_event_id TEXT,
    created_at INT,
    updated_at INT,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT,
    start REAL,
    end REAL,
    speaker TEXT,
    text_ja TEXT,
    text_mt TEXT,
    origin TEXT CHECK(origin IN('live','batch'))
);

CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY,
    event_id TEXT,
    kind TEXT CHECK(kind IN('live','final')),
    lang TEXT,
    text_md TEXT,
    created_at INT
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
    event_id, title, text_ja, text_mt, summary_md, content=''
);

-- アクション項目
CREATE TABLE IF NOT EXISTS action_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT,
    side TEXT CHECK(side IN('client','self')),
    assignee TEXT,
    due_ts INT,
    content TEXT,
    done INT DEFAULT 0
);

-- 議事録本文（Markdown）
CREATE TABLE IF NOT EXISTS minutes (
    event_id TEXT PRIMARY KEY,
    md TEXT,
    updated_at INT
);
"""

_initialized = False

_USER_SELECT = (
    "id,email,password_hash,name,created_at,"
    "google_id,google_access_token,google_refresh_token,google_token_expiry,google_scope"
)


def _user_row_to_dict(row: Optional[Tuple[Any, ...]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {
        "id": row[0],
        "email": row[1],
        "password_hash": row[2],
        "name": row[3] or "",
        "created_at": row[4],
        "google_id": row[5],
        "google_access_token": row[6],
        "google_refresh_token": row[7],
        "google_token_expiry": row[8],
        "google_scope": row[9],
    }


async def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys=ON;")
        await db.executescript(SCHEMA_SQL)
        try:
            async with db.execute("PRAGMA table_info(events)") as cur:
                cols = [r[1] async for r in cur]
            if "participants_json" not in cols:
                await db.execute("ALTER TABLE events ADD COLUMN participants_json TEXT")
            if "user_id" not in cols:
                await db.execute("ALTER TABLE events ADD COLUMN user_id INT")
            if "google_sync_enabled" not in cols:
                await db.execute("ALTER TABLE events ADD COLUMN google_sync_enabled INT NOT NULL DEFAULT 0")
            if "google_event_id" not in cols:
                await db.execute("ALTER TABLE events ADD COLUMN google_event_id TEXT")
        except Exception:
            pass
        try:
            await db.execute("CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id)")
        except Exception:
            pass
        try:
            async with db.execute("PRAGMA table_info(users)") as cur:
                user_cols = [r[1] async for r in cur]
            if "google_id" not in user_cols:
                await db.execute("ALTER TABLE users ADD COLUMN google_id TEXT")
            if "google_access_token" not in user_cols:
                await db.execute("ALTER TABLE users ADD COLUMN google_access_token TEXT")
            if "google_refresh_token" not in user_cols:
                await db.execute("ALTER TABLE users ADD COLUMN google_refresh_token TEXT")
            if "google_token_expiry" not in user_cols:
                await db.execute("ALTER TABLE users ADD COLUMN google_token_expiry INT")
            if "google_scope" not in user_cols:
                await db.execute("ALTER TABLE users ADD COLUMN google_scope TEXT")
        except Exception:
            pass
        try:
            await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id)")
        except Exception:
            pass
        await db.commit()
    global _initialized
    _initialized = True


async def ensure_initialized() -> None:
    global _initialized
    if not _initialized:
        await init_db()


@asynccontextmanager
async def _connect() -> AsyncIterator[aiosqlite.Connection]:
    conn = await aiosqlite.connect(DB_PATH)
    try:
        await conn.execute("PRAGMA foreign_keys=ON;")
        yield conn
    finally:
        await conn.close()


async def _event_accessible(db: aiosqlite.Connection, event_id: str, user_id: Optional[int]) -> bool:
    if user_id is None:
        async with db.execute("SELECT 1 FROM events WHERE id=?", (event_id,)) as cur:
            return await cur.fetchone() is not None
    async with db.execute("SELECT 1 FROM events WHERE id=? AND user_id=?", (event_id, user_id)) as cur:
        return await cur.fetchone() is not None


async def create_user(email: str, password_hash: str, name: str) -> int:
    await ensure_initialized()
    ts = int(time.time())
    async with _connect() as db:
        cur = await db.execute(
            "INSERT INTO users(email,password_hash,name,created_at) VALUES(?,?,?,?)",
            (email, password_hash, name, ts),
        )
        await db.commit()
        return int(cur.lastrowid)


async def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    await ensure_initialized()
    async with _connect() as db:
        async with db.execute(
            f"SELECT {_USER_SELECT} FROM users WHERE email=?",
            (email,),
        ) as cur:
            row = await cur.fetchone()
            return _user_row_to_dict(row)


async def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    await ensure_initialized()
    async with _connect() as db:
        async with db.execute(
            f"SELECT {_USER_SELECT} FROM users WHERE id=?",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
            return _user_row_to_dict(row)


async def get_user_by_google_id(google_id: str) -> Optional[Dict[str, Any]]:
    await ensure_initialized()
    async with _connect() as db:
        async with db.execute(
            f"SELECT {_USER_SELECT} FROM users WHERE google_id=?",
            (google_id,),
        ) as cur:
            row = await cur.fetchone()
            return _user_row_to_dict(row)


async def create_session(user_id: int) -> str:
    await ensure_initialized()
    now = int(time.time())
    sid = uuid.uuid4().hex
    expires = now + SESSION_TTL_SECONDS
    async with _connect() as db:
        await db.execute(
            "INSERT INTO sessions(id,user_id,created_at,expires_at) VALUES(?,?,?,?)",
            (sid, user_id, now, expires),
        )
        await db.commit()
    return sid


async def delete_session(session_id: str) -> None:
    await ensure_initialized()
    async with _connect() as db:
        await db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        await db.commit()


async def get_user_by_session(session_id: str) -> Optional[Dict[str, Any]]:
    await ensure_initialized()
    now = int(time.time())
    async with _connect() as db:
        async with db.execute(
            "SELECT user_id, expires_at FROM sessions WHERE id=?",
            (session_id,),
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            user_id, expires_at = row
            if expires_at < now:
                await db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
                await db.commit()
                return None
        async with db.execute(
            f"SELECT {_USER_SELECT} FROM users WHERE id=?",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
            return _user_row_to_dict(row)


async def touch_session(session_id: str) -> None:
    await ensure_initialized()
    now = int(time.time())
    expires = now + SESSION_TTL_SECONDS
    async with _connect() as db:
        await db.execute(
            "UPDATE sessions SET expires_at=?, created_at=? WHERE id=?",
            (expires, now, session_id),
        )
        await db.commit()


async def update_google_credentials(
    user_id: int,
    google_id: str,
    access_token: Optional[str],
    refresh_token: Optional[str],
    token_expiry: Optional[int],
    scope: Optional[str],
) -> None:
    await ensure_initialized()
    async with _connect() as db:
        await db.execute(
            """
            UPDATE users
            SET google_id=?,
                google_access_token=?,
                google_refresh_token=COALESCE(?, google_refresh_token),
                google_token_expiry=?,
                google_scope=?
            WHERE id=?
            """,
            (
                google_id,
                access_token,
                refresh_token,
                token_expiry,
                scope,
                user_id,
            ),
        )
        await db.commit()


async def create_event(user_id: int, event_id: str, title: str, start_ts: int, end_ts: int, lang: str, translate_to: str) -> None:
    await ensure_initialized()
    ts = int(time.time())
    async with _connect() as db:
        await db.execute(
            "INSERT INTO events(id,user_id,title,start_ts,end_ts,lang,translate_to,audio_path,audio_bytes,participants_json,google_sync_enabled,google_event_id,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, user_id, title, start_ts, end_ts, lang, translate_to, "", 0, "", 0, None, ts, ts),
        )
        await db.execute(
            "INSERT INTO fts(event_id,title,text_ja,text_mt,summary_md) VALUES(?,?,?,?,?)",
            (event_id, title, "", "", ""),
        )
        await db.commit()


async def set_event_ws_token(event_id: str, token: str, user_id: Optional[int] = None) -> bool:
    await ensure_initialized()
    async with _connect() as db:
        params: List[Any] = [f"token:{token}", event_id]
        sql = "UPDATE events SET audio_path=? WHERE id=?"
        if user_id is not None:
            sql += " AND user_id=?"
            params.append(user_id)
        cur = await db.execute(sql, tuple(params))
        await db.commit()
        return cur.rowcount > 0


async def validate_ws_token(event_id: str, token: str, user_id: Optional[int] = None) -> bool:
    await ensure_initialized()
    async with _connect() as db:
        params: List[Any] = [event_id]
        sql = "SELECT audio_path FROM events WHERE id=?"
        if user_id is not None:
            sql += " AND user_id=?"
            params.append(user_id)
        async with db.execute(sql, tuple(params)) as cur:
            row = await cur.fetchone()
            if not row:
                return False
            return row[0] == f"token:{token}"


async def insert_segment(event_id: str, start: float, end: float, speaker: str, text_ja: str, text_mt: str, origin: str, user_id: Optional[int] = None) -> int:
    await ensure_initialized()
    async with _connect() as db:
        if not await _event_accessible(db, event_id, user_id):
            raise PermissionError("event not found")
        cur = await db.execute(
            "INSERT INTO segments(event_id,start,end,speaker,text_ja,text_mt,origin) VALUES(?,?,?,?,?,?,?)",
            (event_id, start, end, speaker, text_ja, text_mt, origin),
        )
        segment_id = int(cur.lastrowid or 0)
        await db.execute(
            "INSERT INTO fts(event_id,title,text_ja,text_mt,summary_md) VALUES(?,?,?,?,?)",
            (event_id, "", text_ja, text_mt or "", ""),
        )
        await db.commit()
        return segment_id


async def delete_segments(
    event_id: str,
    origins: Optional[Iterable[str]] = None,
    user_id: Optional[int] = None,
) -> None:
    """指定イベントのセグメントを削除し、FTSもクリアする。origins未指定なら全削除。"""
    await ensure_initialized()
    origin_list = tuple(origins) if origins else None
    async with _connect() as db:
        if not await _event_accessible(db, event_id, user_id):
            raise PermissionError("event not found")
        params: List[Any] = [event_id]
        sql = "DELETE FROM segments WHERE event_id=?"
        if origin_list:
            placeholders = ",".join("?" for _ in origin_list)
            sql += f" AND origin IN ({placeholders})"
            params.extend(origin_list)
        await db.execute(sql, tuple(params))
        await db.execute("DELETE FROM fts WHERE event_id=?", (event_id,))
        await db.commit()


async def update_segment_end(event_id: str, segment_id: int, end: float, user_id: Optional[int] = None) -> bool:
    await ensure_initialized()
    async with _connect() as db:
        if not await _event_accessible(db, event_id, user_id):
            raise PermissionError("event not found")
        cur = await db.execute(
            "UPDATE segments SET end=? WHERE id=? AND event_id=?",
            (end, segment_id, event_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def list_segments(event_id: str, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    await ensure_initialized()
    async with _connect() as db:
        params: List[Any] = [event_id]
        sql = (
            "SELECT s.id,s.start,s.end,s.speaker,s.text_ja,s.text_mt,s.origin "
            "FROM segments s JOIN events e ON e.id = s.event_id WHERE s.event_id=?"
        )
        if user_id is not None:
            sql += " AND e.user_id=?"
            params.append(user_id)
        sql += " ORDER BY s.start"
        async with db.execute(sql, tuple(params)) as cur:
            rows = await cur.fetchall()
            return [
                {
                    "id": r[0],
                    "start": r[1],
                    "end": r[2],
                    "speaker": r[3],
                    "text_ja": r[4],
                    "text_mt": r[5],
                    "origin": r[6],
                }
                for r in rows
            ]


async def get_event(event_id: str, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    await ensure_initialized()
    async with _connect() as db:
        params: List[Any] = [event_id]
        sql = (
            "SELECT id,user_id,title,start_ts,end_ts,lang,translate_to,audio_path,audio_bytes,participants_json,"
            "google_sync_enabled,google_event_id,created_at,updated_at "
            "FROM events WHERE id=?"
        )
        if user_id is not None:
            sql += " AND user_id=?"
            params.append(user_id)
        async with db.execute(sql, tuple(params)) as cur:
            r = await cur.fetchone()
            if not r:
                return None
            return {
                "id": r[0],
                "user_id": r[1],
                "title": r[2],
                "start_ts": r[3],
                "end_ts": r[4],
                "lang": r[5],
                "translate_to": r[6],
                "audio_path": r[7],
                "audio_bytes": r[8],
                "participants_json": r[9] or "",
                "google_sync_enabled": bool(r[10]),
                "google_event_id": r[11],
                "created_at": r[12],
                "updated_at": r[13],
            }


async def get_latest_summary(event_id: str, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    await ensure_initialized()
    async with _connect() as db:
        if not await _event_accessible(db, event_id, user_id):
            return None
        async with db.execute(
            "SELECT id,kind,lang,text_md,created_at FROM summaries WHERE event_id=? ORDER BY id DESC LIMIT 1",
            (event_id,),
        ) as cur:
            r = await cur.fetchone()
            if not r:
                return None
            return {"id": r[0], "kind": r[1], "lang": r[2], "text_md": r[3], "created_at": r[4]}


async def fts_search(user_id: int, q: str) -> List[Dict[str, Any]]:
    await ensure_initialized()
    q_norm = (q or "").strip()
    async with _connect() as db:
        if q_norm in ("", "*"):
            sql = (
                "SELECT id AS event_id, substr(COALESCE(NULLIF(title,''), id), 1, 200) AS preview "
                "FROM events WHERE user_id=? ORDER BY updated_at DESC, created_at DESC LIMIT 20"
            )
            async with db.execute(sql, (user_id,)) as cur:
                rows = await cur.fetchall()
                return [{"event_id": r[0], "snippet": r[1] or ""} for r in rows]

        sql = (
            "SELECT f.event_id, snippet(fts, 1, '[', ']', '...', 10) "
            "FROM fts f JOIN events e ON e.id = f.event_id WHERE e.user_id=? AND fts MATCH ? LIMIT 20"
        )
        async with db.execute(sql, (user_id, q_norm)) as cur:
            rows = await cur.fetchall()
            return [{"event_id": r[0], "snippet": r[1]} for r in rows]


def _like_pattern(q: str) -> str:
    pattern = (
        q.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
        .replace("'", "''")
    )
    return f"%{pattern}%"


async def search_events_by_title(user_id: int, q: str, limit: int = 20) -> List[Dict[str, Any]]:
    await ensure_initialized()
    q_norm = (q or "").strip()
    async with _connect() as db:
        order_sql = "ORDER BY COALESCE(NULLIF(start_ts,0), created_at) DESC, created_at DESC"
        if q_norm in ("", "*"):
            sql = (
                "SELECT id,title,start_ts,created_at "
                "FROM events WHERE user_id=? "
                f"{order_sql} LIMIT ?"
            )
            params = (user_id, limit)
        else:
            like = _like_pattern(q_norm)
            sql = (
                "SELECT id,title,start_ts,created_at "
                "FROM events "
                "WHERE user_id=? AND (title LIKE ? ESCAPE '\\' OR id LIKE ?) "
                f"{order_sql} LIMIT ?"
            )
            params = (user_id, like, like, limit)
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [
                {
                    "event_id": r[0],
                    "title": r[1] or "",
                    "start_ts": r[2] or 0,
                    "created_at": r[3] or 0,
                }
                for r in rows
            ]


async def set_translate_to(event_id: str, target: str, user_id: Optional[int] = None) -> bool:
    await ensure_initialized()
    async with _connect() as db:
        params: List[Any] = [target, event_id]
        sql = "UPDATE events SET translate_to=? WHERE id=?"
        if user_id is not None:
            sql += " AND user_id=?"
            params.append(user_id)
        cur = await db.execute(sql, tuple(params))
        await db.commit()
        return cur.rowcount > 0


def touch_updated(event_id: str) -> None:
    import sqlite3

    ts = int(time.time())
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute("UPDATE events SET updated_at=? WHERE id=?", (ts, event_id))
        con.commit()
    finally:
        con.close()


async def delete_event(event_id: str, user_id: Optional[int] = None) -> bool:
    await ensure_initialized()
    async with _connect() as db:
        if not await _event_accessible(db, event_id, user_id):
            return False
        await db.execute("DELETE FROM segments WHERE event_id=?", (event_id,))
        await db.execute("DELETE FROM summaries WHERE event_id=?", (event_id,))
        await db.execute("DELETE FROM fts WHERE event_id=?", (event_id,))
        await db.execute("DELETE FROM action_items WHERE event_id=?", (event_id,))
        await db.execute("DELETE FROM minutes WHERE event_id=?", (event_id,))
        await db.execute("DELETE FROM events WHERE id=?", (event_id,))
        await db.commit()
        return True


async def list_events_range(user_id: int, ts_from: Optional[int] = None, ts_to: Optional[int] = None, limit: int = 500) -> List[Dict[str, Any]]:
    await ensure_initialized()
    q = (
        "SELECT id,title,start_ts,end_ts,lang,translate_to,participants_json,google_sync_enabled,google_event_id,created_at,updated_at "
        "FROM events WHERE user_id=?"
    )
    args: List[Any] = [user_id]
    if ts_from is not None:
        q += " AND (start_ts >= ? OR (end_ts>0 AND end_ts>=?))"
        args.extend([ts_from, ts_from])
    if ts_to is not None:
        q += " AND (start_ts <= ?)"
        args.append(ts_to)
    q += " ORDER BY start_ts DESC, updated_at DESC LIMIT ?"
    args.append(limit)

    async with _connect() as db:
        async with db.execute(q, tuple(args)) as cur:
            rows = await cur.fetchall()
            return [
                {
                    "id": r[0],
                    "title": r[1],
                    "start_ts": r[2],
                    "end_ts": r[3],
                    "lang": r[4],
                    "translate_to": r[5],
                    "participants_json": r[6] or "",
                    "google_sync_enabled": bool(r[7]),
                    "google_event_id": r[8],
                    "created_at": r[9],
                    "updated_at": r[10],
                }
                for r in rows
            ]


async def list_events(limit: int = 50) -> List[Dict[str, Any]]:
    await ensure_initialized()
    async with _connect() as db:
        async with db.execute(
            "SELECT id,title,start_ts,end_ts,lang,translate_to,participants_json,google_sync_enabled,google_event_id,created_at,updated_at "
            "FROM events ORDER BY start_ts DESC, updated_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
            return [
                {
                    "id": r[0],
                    "title": r[1],
                    "start_ts": r[2],
                    "end_ts": r[3],
                    "lang": r[4],
                    "translate_to": r[5],
                    "participants_json": r[6] or "",
                    "google_sync_enabled": bool(r[7]),
                    "google_event_id": r[8],
                    "created_at": r[9],
                    "updated_at": r[10],
                }
                for r in rows
            ]


async def update_event_fields(
    event_id: str,
    *,
    user_id: Optional[int] = None,
    title: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    lang: Optional[str] = None,
    translate_to: Optional[str] = None,
    participants_json: Optional[str] = None,
    google_sync_enabled: Optional[bool] = None,
    google_event_id: Optional[Optional[str]] = None,
) -> bool:
    await ensure_initialized()
    sets: List[str] = []
    args: List[Any] = []
    if title is not None:
        sets.append("title=?")
        args.append(title)
    if start_ts is not None:
        sets.append("start_ts=?")
        args.append(start_ts)
    if end_ts is not None:
        sets.append("end_ts=?")
        args.append(end_ts)
    if lang is not None:
        sets.append("lang=?")
        args.append(lang)
    if translate_to is not None:
        sets.append("translate_to=?")
        args.append(translate_to)
    if participants_json is not None:
        sets.append("participants_json=?")
        args.append(participants_json)
    if google_sync_enabled is not None:
        sets.append("google_sync_enabled=?")
        args.append(1 if google_sync_enabled else 0)
    if google_event_id is not None:
        sets.append("google_event_id=?")
        args.append(google_event_id)
    if not sets:
        return True
    sets.append("updated_at=?")
    args.append(int(time.time()))
    args.append(event_id)
    sql = f"UPDATE events SET {', '.join(sets)} WHERE id=?"
    if user_id is not None:
        sql += " AND user_id=?"
        args.append(user_id)
    async with _connect() as db:
        cur = await db.execute(sql, tuple(args))
        await db.commit()
        return cur.rowcount > 0


async def set_event_google_sync(event_id: str, user_id: Optional[int], enabled: bool, google_event_id: Optional[str]) -> bool:
    return await update_event_fields(
        event_id,
        user_id=user_id,
        google_sync_enabled=enabled,
        google_event_id=google_event_id,
    )


async def get_minutes(event_id: str, user_id: Optional[int] = None) -> str:
    await ensure_initialized()
    async with _connect() as db:
        if not await _event_accessible(db, event_id, user_id):
            raise PermissionError("event not found")
        async with db.execute("SELECT md FROM minutes WHERE event_id=?", (event_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row and row[0] else ""


async def set_minutes(event_id: str, md: str, user_id: Optional[int] = None) -> bool:
    await ensure_initialized()
    ts = int(time.time())
    async with _connect() as db:
        if not await _event_accessible(db, event_id, user_id):
            return False
        await db.execute(
            "INSERT INTO minutes(event_id,md,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(event_id) DO UPDATE SET md=excluded.md, updated_at=excluded.updated_at",
            (event_id, md, ts),
        )
        await db.execute(
            "INSERT INTO fts(event_id,title,text_ja,text_mt,summary_md) VALUES(?,?,?,?,?)",
            (event_id, "", "", "", md or ""),
        )
        await db.commit()
        return True


async def list_actions(event_id: str, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    await ensure_initialized()
    async with _connect() as db:
        if not await _event_accessible(db, event_id, user_id):
            return []
        async with db.execute(
            "SELECT id,side,assignee,due_ts,content,done FROM action_items WHERE event_id=? ORDER BY id",
            (event_id,),
        ) as cur:
            rows = await cur.fetchall()
            return [
                {
                    "id": r[0],
                    "side": r[1],
                    "assignee": r[2],
                    "due_ts": r[3],
                    "content": r[4],
                    "done": r[5],
                }
                for r in rows
            ]


async def create_action(event_id: str, side: str, assignee: str, due_ts: int, content: str, user_id: Optional[int] = None) -> Optional[int]:
    await ensure_initialized()
    async with _connect() as db:
        if not await _event_accessible(db, event_id, user_id):
            return None
        cur = await db.execute(
            "INSERT INTO action_items(event_id,side,assignee,due_ts,content,done) VALUES(?,?,?,?,?,0)",
            (event_id, side, assignee, due_ts, content),
        )
        await db.commit()
        return cur.lastrowid or 0


async def update_action(
    event_id: str,
    action_id: int,
    *,
    user_id: Optional[int] = None,
    side: Optional[str] = None,
    assignee: Optional[str] = None,
    due_ts: Optional[int] = None,
    content: Optional[str] = None,
    done: Optional[int] = None,
) -> bool:
    await ensure_initialized()
    sets: List[str] = []
    args: List[Any] = []
    if side is not None:
        sets.append("side=?")
        args.append(side)
    if assignee is not None:
        sets.append("assignee=?")
        args.append(assignee)
    if due_ts is not None:
        sets.append("due_ts=?")
        args.append(due_ts)
    if content is not None:
        sets.append("content=?")
        args.append(content)
    if done is not None:
        sets.append("done=?")
        args.append(done)
    if not sets:
        return True
    args.extend([event_id, action_id])
    sql = "UPDATE action_items SET " + ", ".join(sets) + " WHERE event_id=? AND id=?"
    async with _connect() as db:
        if user_id is not None and not await _event_accessible(db, event_id, user_id):
            return False
        cur = await db.execute(sql, tuple(args))
        await db.commit()
        return cur.rowcount > 0


async def delete_action(event_id: str, action_id: int, user_id: Optional[int] = None) -> bool:
    await ensure_initialized()
    async with _connect() as db:
        if user_id is not None and not await _event_accessible(db, event_id, user_id):
            return False
        cur = await db.execute(
            "DELETE FROM action_items WHERE event_id=? AND id=?",
            (event_id, action_id),
        )
        await db.commit()
        return cur.rowcount > 0
