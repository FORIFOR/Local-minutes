from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from authlib.integrations.starlette_client import OAuth
from urllib.parse import quote

from ..config import settings
from ..db import get_db
from ..models.user import User
from ..security import create_access_token, set_auth_cookie

router = APIRouter()

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id or None,
    client_secret=settings.google_client_secret or None,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile",
    },
)


@router.get("/google/login")
async def google_login(request: Request):
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth is not configured")
    redirect_uri = settings.google_redirect_uri
    if not redirect_uri:
        raise HTTPException(status_code=500, detail="GOOGLE_REDIRECT_URI is not configured")
    next_path = request.query_params.get("next") or "/"
    request.session["google_next"] = next_path
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth is not configured")
    token = await oauth.google.authorize_access_token(request)
    profile = token.get("userinfo") or {}
    google_id = profile.get("sub") or profile.get("id")
    email = profile.get("email")
    if not google_id or not email:
        raise HTTPException(status_code=400, detail="Failed to fetch Google profile")
    name = profile.get("name") or email.split("@")[0]

    user = db.query(User).filter(User.google_id == google_id).first()
    if not user:
        user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, name=name, google_id=google_id)
        db.add(user)
    user.google_id = google_id
    user.google_access_token = token.get("access_token")
    user.google_refresh_token = token.get("refresh_token") or user.google_refresh_token
    user.google_scope = token.get("scope")
    db.commit()
    db.refresh(user)

    access_token = create_access_token(user.id)
    next_path = request.session.pop("google_next", "/")
    redirect_to = settings.google_login_redirect_url or "/"
    base_url = f"{settings.frontend_origin.rstrip('/')}{redirect_to}"
    separator = "&" if "?" in base_url else "?"
    target = f"{base_url}{separator}next={quote(next_path, safe='/')}"
    response = RedirectResponse(url=target)
    set_auth_cookie(response, access_token)
    return response
