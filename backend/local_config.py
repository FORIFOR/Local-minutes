from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class LocalSettings:
    cloud_api_base: str = os.getenv("CLOUD_API_BASE", "").strip()
    cloud_api_token: str = os.getenv("CLOUD_API_TOKEN", "").strip()
    cloud_sync_enabled: bool = _env_bool("CLOUD_SYNC_ENABLED", False)
    cloud_sync_timeout_sec: float = _env_float("CLOUD_SYNC_TIMEOUT_SEC", 30.0)
    cloud_sync_attach_segments: bool = _env_bool("CLOUD_SYNC_ATTACH_SEGMENTS", False)


@lru_cache()
def get_local_settings() -> LocalSettings:
    return LocalSettings()


settings = get_local_settings()
