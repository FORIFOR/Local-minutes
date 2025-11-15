import base64
import json
import os
import secrets
import time
import uuid
from typing import Any, Dict, Optional

try:
    from authlib.integrations.starlette_client import OAuth, OAuthError  # type: ignore
    _AUTHLIB_AVAILABLE = True
except ModuleNotFoundError:
    OAuth = None  # type: ignore
    class OAuthError(Exception):  # type: ignore
        pass
    _AUTHLIB_AVAILABLE = False
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field

from backend.api.deps import SESSION_COOKIE_NAME, AuthUser, get_current_user
from backend.store import db
from backend.store.db import SESSION_TTL_SECONDS

router = APIRouter()

pwd_context = CryptContext(
    schemes=["bcrypt_sha256", "bcrypt"],
    deprecated="auto",
)  # use bcrypt_sha256 for long passwords while keeping legacy hashes valid

_SESSION_SECURE_DEFAULT = os.getenv("M4_SESSION_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes", "on"}
_SESSION_SAMESITE = os.getenv("M4_SESSION_COOKIE_SAMESITE", "lax") or "lax"

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
GOOGLE_LOGIN_REDIRECT_URL = os.getenv("GOOGLE_LOGIN_REDIRECT_URL", "/") or "/"
GOOGLE_OAUTH_SCOPE = os.getenv("GOOGLE_OAUTH_SCOPE", "openid email profile").strip() or "openid email profile"

_oauth: Optional[OAuth] = None
_google_client = None
if _AUTHLIB_AVAILABLE and GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    _oauth = OAuth()
    _google_client = _oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": GOOGLE_OAUTH_SCOPE},
    )


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _set_session_cookie(resp: JSONResponse, session_id: str) -> None:
    resp.set_cookie(
        SESSION_COOKIE_NAME,
        session_id,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=_SESSION_SECURE_DEFAULT,
        samesite=_SESSION_SAMESITE,  # type: ignore[arg-type]
        path="/",
    )


def _clear_session_cookie(resp: JSONResponse) -> None:
    resp.delete_cookie(SESSION_COOKIE_NAME, path="/")


def _encode_state(data: Dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8")


def _decode_state(value: Optional[str]) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        raw = base64.urlsafe_b64decode(value.encode("utf-8"))
        return json.loads(raw)
    except Exception:
        return {}


def _sanitize_next_url(value: Optional[str]) -> str:
    if not value:
        return GOOGLE_LOGIN_REDIRECT_URL or "/"
    value = value.strip()
    if not value:
        return GOOGLE_LOGIN_REDIRECT_URL or "/"
    if value.startswith("http://") or value.startswith("https://"):
        return GOOGLE_LOGIN_REDIRECT_URL or "/"
    if not value.startswith("/"):
        value = "/" + value
    return value


def _google_redirect_uri(request: Request) -> str:
    if GOOGLE_REDIRECT_URI:
        return GOOGLE_REDIRECT_URI
    return str(request.url_for("google_callback"))


async def _issue_session_response(user_id: int, email: str, name: str, response: Optional[Response] = None) -> Response:
    session_id = await db.create_session(user_id)
    if response is None:
        response = JSONResponse({"id": user_id, "email": email, "name": name})
    _set_session_cookie(response, session_id)
    return response


class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: Optional[str] = Field(default="", max_length=100)


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


def _token_expiry_ts(token: Dict[str, Any]) -> Optional[int]:
    exp = token.get("expires_at")
    if isinstance(exp, (int, float)):
        return int(exp)
    expires_in = token.get("expires_in")
    if isinstance(expires_in, (int, float)):
        return int(time.time() + expires_in)
    return None


def _random_password_hash() -> str:
    return pwd_context.hash(secrets.token_hex(16))


async def _upsert_google_user(profile: Dict[str, Any], token: Dict[str, Any]) -> Dict[str, Any]:
    google_id = profile.get("sub") or profile.get("id")
    if not google_id:
        raise HTTPException(status_code=400, detail="GoogleアカウントIDの取得に失敗しました")
    email_raw = profile.get("email")
    if not email_raw:
        raise HTTPException(status_code=400, detail="Googleアカウントにメールアドレスがありません")
    email = _normalize_email(email_raw)
    display_name = (profile.get("name") or email.split("@")[0]).strip()

    user = await db.get_user_by_google_id(google_id)
    if not user and email:
        user = await db.get_user_by_email(email)
    if not user:
        placeholder = _random_password_hash()
        user_id = await db.create_user(email, placeholder, display_name)
        user = await db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=500, detail="ユーザー作成に失敗しました")

    user_id = int(user["id"])
    expires_at = _token_expiry_ts(token)
    await db.update_google_credentials(
        user_id,
        google_id,
        token.get("access_token"),
        token.get("refresh_token"),
        expires_at,
        token.get("scope"),
    )
    updated = await db.get_user_by_id(user_id)
    return updated or user


@router.post("/api/auth/register")
async def register(body: RegisterBody) -> JSONResponse:
    email = _normalize_email(body.email)
    existing = await db.get_user_by_email(email)
    if existing:
        raise HTTPException(status_code=409, detail="このメールアドレスは既に登録されています")
    hashed = pwd_context.hash(body.password)
    display_name = (body.name or "").strip() or email.split("@")[0]
    user_id = await db.create_user(email, hashed, display_name)
    return await _issue_session_response(user_id, email, display_name)


@router.post("/api/auth/login")
async def login(body: LoginBody) -> JSONResponse:
    email = _normalize_email(body.email)
    user = await db.get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=401, detail="メールアドレスまたはパスワードが違います")
    if not pwd_context.verify(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="メールアドレスまたはパスワードが違います")
    return await _issue_session_response(int(user["id"]), email, user.get("name") or "")


@router.get("/api/auth/google/login")
async def google_login(request: Request) -> Response:
    if _google_client is None:
        raise HTTPException(status_code=503, detail="Google OAuth が設定されていません")
    next_url = _sanitize_next_url(request.query_params.get("next"))
    state = _encode_state({"next": next_url})
    redirect_uri = _google_redirect_uri(request)
    return await _google_client.authorize_redirect(request, redirect_uri, state=state)


@router.get("/api/auth/google/callback", name="google_callback")
async def google_callback(request: Request) -> Response:
    if _google_client is None:
        raise HTTPException(status_code=503, detail="Google OAuth が設定されていません")
    try:
        token = await _google_client.authorize_access_token(request)
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=f"Google認証に失敗しました: {exc.error}") from exc

    userinfo = token.get("userinfo")
    if not userinfo:
        resp = await _google_client.get("userinfo", token=token)
        userinfo = resp.json()
    if not isinstance(userinfo, dict):
        raise HTTPException(status_code=400, detail="Googleユーザー情報の取得に失敗しました")

    user = await _upsert_google_user(userinfo, token)
    state_data = _decode_state(request.query_params.get("state"))
    target = _sanitize_next_url(state_data.get("next"))
    redirect = RedirectResponse(url=target, status_code=303)
    return await _issue_session_response(
        int(user["id"]),
        user.get("email") or userinfo.get("email") or "",
        user.get("name") or userinfo.get("name") or "",
        response=redirect,
    )


@router.post("/api/auth/logout")
async def logout(request: Request) -> JSONResponse:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        await db.delete_session(session_id)
    resp = JSONResponse({"ok": True})
    _clear_session_cookie(resp)
    return resp


@router.get("/api/auth/me")
async def me(user: AuthUser = Depends(get_current_user)) -> Dict[str, Any]:
    return {"id": user.id, "email": user.email, "name": user.name}
