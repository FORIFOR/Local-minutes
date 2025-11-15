from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr

from backend.store import db

SESSION_COOKIE_NAME = "m4_session"


class AuthUser(BaseModel):
    id: int
    email: EmailStr
    name: str
    session_id: str


async def _resolve_session(session_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not session_id:
        return None
    user = await db.get_user_by_session(session_id)
    if not user:
        return None
    return {
        "id": int(user["id"]),
        "email": user["email"],
        "name": user.get("name") or "",
        "session_id": session_id,
    }


async def get_current_user(request: Request) -> AuthUser:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    user = await _resolve_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="認証が必要です")
    return AuthUser(**user)


async def get_optional_user(request: Request) -> Optional[AuthUser]:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    user = await _resolve_session(session_id)
    return AuthUser(**user) if user else None
