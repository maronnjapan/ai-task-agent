from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ChatCreate(BaseModel):
    title: str | None = None


class ChatOut(ORMModel):
    id: str
    task_id: str
    title: str
    created_at: str
    message_count: int = 0
    last_message_at: str | None = None


class MessageCreate(BaseModel):
    content: str = Field(min_length=1)
    author_type: str = "user"
    reply: bool = True  # ask the AI to respond


class MessageOut(ORMModel):
    id: str
    chat_id: str
    author_type: str
    content: str
    created_at: str


class MessagePage(BaseModel):
    items: list[MessageOut]
    has_more: bool
    next_before: str | None = None


class DecisionCreate(BaseModel):
    content: str = Field(min_length=1)
    source_message_id: str | None = None
    supersedes_id: str | None = None


class DecisionOut(ORMModel):
    id: str
    task_id: str
    content: str
    source_message_id: str | None
    supersedes_id: str | None
    status: str
    decided_by: str
    decided_at: str


class InstructionRequest(BaseModel):
    instruction: str = Field(min_length=1)
    task_ids: list[str] = Field(default_factory=list)


class InstructionOut(BaseModel):
    run_id: str
    status: str
    response: str
    changes: list[dict] = Field(default_factory=list)
