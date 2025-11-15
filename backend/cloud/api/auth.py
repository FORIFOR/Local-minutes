from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.cloud.db import get_db
from backend.cloud.models.user import User
from backend.cloud.security import get_current_user

router = APIRouter()


@router.get("/me")
def read_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
    }


@router.post("/login")
def email_login_not_supported() -> None:
    raise HTTPException(status_code=400, detail="Email/password login is not supported. Use Google login.")


@router.post("/register")
def email_register_not_supported() -> None:
    raise HTTPException(status_code=400, detail="Email/password registration is not supported. Use Google login.")
