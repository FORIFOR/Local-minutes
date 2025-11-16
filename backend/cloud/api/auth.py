from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from backend.cloud.db import get_db
from backend.cloud.models.user import User
from backend.cloud.security import (
    clear_auth_cookie,
    get_current_user,
    hash_password,
    set_auth_cookie,
    user_payload,
    verify_password,
    create_access_token,
)

router = APIRouter()

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class MeResponse(BaseModel):
    id: int
    email: EmailStr
    name: str | None = None

    class Config:
        orm_mode = True


@router.get("/me", response_model=MeResponse)
def read_me(user: User = Depends(get_current_user)) -> User:
    return user


def _make_auth_response(user: User) -> JSONResponse:
    token = create_access_token(user.id)
    payload = user_payload(user)
    payload["token"] = token
    response = JSONResponse(payload)
    set_auth_cookie(response, token)
    return response


@router.post("/register", response_model=MeResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if user:
        if user.password_hash:
            raise HTTPException(status_code=400, detail="This email is already registered.")
        user.password_hash = hash_password(body.password)
        if body.name:
            user.name = body.name
    else:
        user = User(
            email=body.email,
            name=body.name,
            password_hash=hash_password(body.password),
        )
        db.add(user)
    db.commit()
    db.refresh(user)
    return _make_auth_response(user)


@router.post("/login", response_model=MeResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return _make_auth_response(user)


@router.post("/logout")
def logout() -> JSONResponse:
    response = JSONResponse({"ok": True})
    clear_auth_cookie(response)
    return response
