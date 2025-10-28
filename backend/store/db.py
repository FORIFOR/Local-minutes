import os
import aiosqlite
import time
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = os.path.join("backend", "data", "app.db")


SCHEMA_SQL = r"""
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  title TEXT,
  start_ts INT,
  end_ts INT,
  lang TEXT,
  translate_to TEXT,
  audio_path TEXT,
  audio_bytes INT,
  participants_json TEXT,
  created_at INT,
  updated_at INT
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


async def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA_SQL)
        # 既存DBへのマイグレーション: participants_json 列が無ければ追加
        try:
            async with db.execute("PRAGMA table_info(events)") as cur:
                cols = [r[1] async for r in cur]
            if "participants_json" not in cols:
                await db.execute("ALTER TABLE events ADD COLUMN participants_json TEXT")
        except Exception:
            pass
        await db.commit()
    global _initialized
    _initialized = True


async def ensure_initialized() -> None:
    global _initialized
    if not _initialized:
        await init_db()


async def create_event(event_id: str, title: str, start_ts: int, end_ts: int, lang: str, translate_to: str):
    await ensure_initialized()
    ts = int(time.time())
    await ensure_initialized()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO events(id,title,start_ts,end_ts,lang,translate_to,audio_path,audio_bytes,participants_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, title, start_ts, end_ts, lang, translate_to, "", 0, "", ts, ts),
        )
        await db.execute(
            "INSERT INTO fts(event_id,title,text_ja,text_mt,summary_md) VALUES(?,?,?,?,?)",
            (event_id, title, "", "", ""),
        )
        await db.commit()


async def set_event_ws_token(event_id: str, token: str):
    # 簡易: events.audio_path に一時的にトークンを保存(別カラムでも良い)
    await ensure_initialized()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE events SET audio_path=? WHERE id=?", (f"token:{token}", event_id))
        await db.commit()


async def validate_ws_token(event_id: str, token: str) -> bool:
    await ensure_initialized()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT audio_path FROM events WHERE id=?", (event_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return False
            return row[0] == f"token:{token}"


async def insert_segment(event_id: str, start: float, end: float, speaker: str, text_ja: str, text_mt: str, origin: str):
    await ensure_initialized()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO segments(event_id,start,end,speaker,text_ja,text_mt,origin) VALUES(?,?,?,?,?,?,?)",
            (event_id, start, end, speaker, text_ja, text_mt, origin),
        )
        # FTS 同期: テキストのみ追記連結
        await db.execute(
            "INSERT INTO fts(event_id,title,text_ja,text_mt,summary_md) VALUES(?,?,?,?,?)",
            (event_id, "", text_ja, text_mt or "", ""),
        )
        await db.commit()


async def list_segments(event_id: str) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id,start,end,speaker,text_ja,text_mt,origin FROM segments WHERE event_id=? ORDER BY start", (event_id,)
        ) as cur:
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


async def get_event(event_id: str) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id,title,start_ts,end_ts,lang,translate_to,audio_path,audio_bytes,participants_json,created_at,updated_at FROM events WHERE id=?",
            (event_id,),
        ) as cur:
            r = await cur.fetchone()
            if not r:
                return None
            return {
                "id": r[0],
                "title": r[1],
                "start_ts": r[2],
                "end_ts": r[3],
                "lang": r[4],
                "translate_to": r[5],
                "audio_path": r[6],
                "audio_bytes": r[7],
                "participants_json": r[8] or "",
                "created_at": r[9],
                "updated_at": r[10],
            }


async def get_latest_summary(event_id: str) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id,kind,lang,text_md,created_at FROM summaries WHERE event_id=? ORDER BY id DESC LIMIT 1",
            (event_id,),
        ) as cur:
            r = await cur.fetchone()
            if not r:
                return None
            return {"id": r[0], "kind": r[1], "lang": r[2], "text_md": r[3], "created_at": r[4]}


async def fts_search(q: str) -> List[Dict[str, Any]]:
    """FTS検索。

    注意:
    - FTS5 は単独の '*' をクエリに受け付けないため、その場合(または空白のみ)は
      フォールバックとして最新イベントのプレビューを返す。
    - 通常の検索は MATCH プレースホルダで安全に実行する。
    """
    q_norm = (q or "").strip()
    async with aiosqlite.connect(DB_PATH) as db:
        # フォールバック: 全件/最新(初期表示などで q='*' を想定)
        if q_norm == "" or q_norm == "*":
            # FTS(content='') はカラムを保持しないため、初期表示は events から最新順を返す
            sql = (
                """
                SELECT id AS event_id,
                       substr(COALESCE(NULLIF(title,''), id), 1, 200) AS preview
                  FROM events
              ORDER BY updated_at DESC, created_at DESC
                 LIMIT 20
                """
            )
            async with db.execute(sql) as cur:
                rows = await cur.fetchall()
                return [{"event_id": r[0], "snippet": r[1] or ""} for r in rows]

        # 通常の FTS 検索
        async with db.execute(
            "SELECT event_id, snippet(fts, 1, '[', ']', '...', 10) FROM fts WHERE fts MATCH ? LIMIT 20",
            (q_norm,),
        ) as cur:
            rows = await cur.fetchall()
    return [{"event_id": r[0], "snippet": r[1]} for r in rows]


async def set_translate_to(event_id: str, target: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE events SET translate_to=? WHERE id=?", (target, event_id))
        await db.commit()


def touch_updated(event_id: str):
    import sqlite3
    ts = int(time.time())
    con = sqlite3.connect(DB_PATH)
    con.execute("UPDATE events SET updated_at=? WHERE id=?", (ts, event_id))
    con.commit()
    con.close()


async def delete_event(event_id: str) -> None:
    """イベントと関連データを削除する。
    対象: events, segments, summaries, fts
    """
    await ensure_initialized()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM segments WHERE event_id=?", (event_id,))
        await db.execute("DELETE FROM summaries WHERE event_id=?", (event_id,))
        await db.execute("DELETE FROM fts WHERE event_id=?", (event_id,))
        await db.execute("DELETE FROM events WHERE id=?", (event_id,))
        await db.commit()


async def list_events_range(ts_from: Optional[int] = None, ts_to: Optional[int] = None, limit: int = 500) -> List[Dict[str, Any]]:
    """時間範囲でイベントを列挙する。
    - ts_from/ts_to いずれかが None の場合は片側のみでフィルタ
    - end_ts が 0 の場合は start_ts+3600 を仮の終了とみなす
    """
    await ensure_initialized()
    q = (
        "SELECT id,title,start_ts,end_ts,lang,translate_to,participants_json,created_at,updated_at FROM events"
    )
    conds = []
    args: list = []
    if ts_from is not None:
        conds.append("(start_ts >= ? OR (end_ts>0 AND end_ts>=?))")
        args += [ts_from, ts_from]
    if ts_to is not None:
        conds.append("(start_ts <= ?)")
        args += [ts_to]
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY start_ts DESC, updated_at DESC LIMIT ?"
    args.append(limit)
    out: List[Dict[str, Any]] = []

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(q, tuple(args)) as cur:
            rows = await cur.fetchall()
            for r in rows:
                out.append({
                    "id": r[0],
                    "title": r[1],
                    "start_ts": r[2],
                    "end_ts": r[3],
                    "lang": r[4],
                    "translate_to": r[5],
                    "participants_json": r[6] or "",
                    "created_at": r[7],
                    "updated_at": r[8],
                })
    return out


async def update_event_fields(event_id: str, title: Optional[str] = None, start_ts: Optional[int] = None, end_ts: Optional[int] = None, lang: Optional[str] = None, translate_to: Optional[str] = None, participants_json: Optional[str] = None) -> bool:
    await ensure_initialized()
    sets = []
    args: list = []
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
    if not sets:
        return True
    # updated_at を常に更新
    sets.append("updated_at=?")
    import time as _t
    args.append(int(_t.time()))
    args.append(event_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(f"UPDATE events SET {', '.join(sets)} WHERE id=?", tuple(args))
        await db.commit()
        return cur.rowcount > 0


# 議事録本文の取得/保存
async def get_minutes(event_id: str) -> str:
    await ensure_initialized()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT md FROM minutes WHERE event_id=?", (event_id,)) as cur:
            r = await cur.fetchone()
            return r[0] if r and r[0] else ""


async def set_minutes(event_id: str, md: str) -> None:
    await ensure_initialized()
    ts = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        # UPSERT
        await db.execute(
            "INSERT INTO minutes(event_id,md,updated_at) VALUES(?,?,?) ON CONFLICT(event_id) DO UPDATE SET md=excluded.md, updated_at=excluded.updated_at",
            (event_id, md, ts),
        )
        # FTS にも minutes を反映（summary_md欄に投入）
        await db.execute(
            "INSERT INTO fts(event_id,title,text_ja,text_mt,summary_md) VALUES(?,?,?,?,?)",
            (event_id, "", "", "", md or ""),
        )
        await db.commit()


# アクション項目 CRUD
async def list_actions(event_id: str) -> List[Dict[str, Any]]:
    await ensure_initialized()
    async with aiosqlite.connect(DB_PATH) as db:
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


async def create_action(event_id: str, side: str, assignee: str, due_ts: int, content: str) -> int:
    await ensure_initialized()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO action_items(event_id,side,assignee,due_ts,content,done) VALUES(?,?,?,?,?,0)",
            (event_id, side, assignee, due_ts, content),
        )
        await db.commit()
        return cur.lastrowid or 0


async def update_action(event_id: str, action_id: int, side: Optional[str] = None, assignee: Optional[str] = None, due_ts: Optional[int] = None, content: Optional[str] = None, done: Optional[int] = None) -> bool:
    await ensure_initialized()
    sets = []
    args: list = []
    if side is not None:
        sets.append("side=?"); args.append(side)
    if assignee is not None:
        sets.append("assignee=?"); args.append(assignee)
    if due_ts is not None:
        sets.append("due_ts=?"); args.append(due_ts)
    if content is not None:
        sets.append("content=?"); args.append(content)
    if done is not None:
        sets.append("done=?"); args.append(done)
    if not sets:
        return True
    args += [event_id, action_id]
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            f"UPDATE action_items SET {', '.join(sets)} WHERE event_id=? AND id=?",
            tuple(args),
        )
        await db.commit()
        return cur.rowcount > 0


async def delete_action(event_id: str, action_id: int) -> bool:
    await ensure_initialized()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM action_items WHERE event_id=? AND id=?", (event_id, action_id))
        await db.commit()
        return cur.rowcount > 0
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(q, tuple(args)) as cur:
            async for r in cur:
                out.append({
                    "id": r[0],
                    "title": r[1],
                    "start_ts": r[2],
                    "end_ts": r[3],
                    "lang": r[4],
                    "translate_to": r[5],
                    "created_at": r[6],
                    "updated_at": r[7],
                })
    return out
