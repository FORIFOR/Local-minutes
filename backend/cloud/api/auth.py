from __future__ import annotations

from fastapi import APIRouter, Depends
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
