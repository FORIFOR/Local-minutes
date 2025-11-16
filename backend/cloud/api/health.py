from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.cloud.db import get_db

router = APIRouter()


@router.get("/models")
def health_models(db: Session = Depends(get_db)) -> dict:
    """フロントのヘルスカード向けの簡易状態を返す。"""
    try:
        db.execute("SELECT 1")
        db_status = "ok"
    except Exception:
        db_status = "error"

    return {
        "status": db_status,
        "db": db_status,
        "models": [
            {
                "name": "cloud-backend",
                "kind": "api",
                "status": db_status,
                "details": "Cloud backend is reachable",
            }
        ],
    }
