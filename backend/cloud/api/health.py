from __future__ import annotations

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.cloud.db import get_db

router = APIRouter()


@router.get("/models")
def health_models(db: Session = Depends(get_db)) -> dict:
    """フロントのdashboardが期待する旧フォーマットに合わせたモデル健診"""
    checks = []
    try:
        db.execute("SELECT 1")
        checks.append({"name": "DB接続", "path": "database", "ok": True, "issues": []})
    except Exception as exc:  # pragma: no cover
        checks.append({"name": "DB接続", "path": "database", "ok": False, "issues": [str(exc)]})

    checks.append(
        {
            "name": "クラウドAPI",
            "path": "/api/events",
            "ok": True,
            "issues": [],
        }
    )
    ok_count = sum(1 for c in checks if c["ok"])
    summary = f"{ok_count}/{len(checks)} モジュールが利用可能"
    return {"ok": ok_count == len(checks), "checks": checks, "summary": summary}
