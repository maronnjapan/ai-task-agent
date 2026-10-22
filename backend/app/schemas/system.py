from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SystemStatusOut(BaseModel):
    version: str
    platform: dict[str, Any]
    data_directory: str
    database_path: str
    uptime_seconds: float
    manager: dict[str, Any]
    counts: dict[str, int]
    sse_subscribers: int
    autostart_installed: bool
    pid: int
    secret_backend: str


class BackupRequest(BaseModel):
    directory: str | None = None
    label: str | None = None


class BackupOut(BaseModel):
    path: str
    size_bytes: int
    created_at: str
    includes: list[str] = Field(default_factory=list)


class RestoreRequest(BaseModel):
    path: str
    confirm: bool = False


class RestoreOut(BaseModel):
    restored_from: str
    safety_backup: str
    message: str


class AutostartRequest(BaseModel):
    enabled: bool
