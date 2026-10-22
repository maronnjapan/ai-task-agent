from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Message(BaseModel):
    ok: bool = True
    message: str = ""
    data: dict[str, Any] | None = None


class Page(BaseModel):
    items: list[Any]
    total: int
    limit: int
    offset: int
