from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import MemoryKind, MemoryScope
from app.schemas.common import ORMModel


class MemoryCreate(BaseModel):
    scope: MemoryScope = MemoryScope.GLOBAL
    category_id: str | None = None
    task_id: str | None = None
    content: str = Field(min_length=1)
    source: str | None = None
    kind: MemoryKind = MemoryKind.RESEARCH
    confirmed: bool = False


class MemoryUpdate(BaseModel):
    content: str | None = None
    source: str | None = None
    kind: MemoryKind | None = None
    confirmed: bool | None = None


class MemoryOut(ORMModel):
    id: str
    scope: str
    category_id: str | None
    task_id: str | None
    content: str
    source: str | None
    kind: str
    confirmed: bool
    created_at: str
    updated_at: str


class UserStateUpdate(BaseModel):
    condition: str = Field(max_length=200)
    expires_in_minutes: int | None = Field(default=None, ge=1)
    source: str = "user"


class UserStateOut(ORMModel):
    condition: str
    source: str
    expires_at: str | None
    updated_at: str
    active: bool = True
