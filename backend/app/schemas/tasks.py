from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import Assignee, TaskStatus
from app.schemas.common import ORMModel


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class CategoryUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class CategoryOut(ORMModel):
    id: str
    name: str
    created_at: str
    task_count: int = 0


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    due_at: str | None = None
    category_id: str | None = None
    status: TaskStatus = TaskStatus.TODO
    assignee: Assignee = Assignee.SHARED


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    due_at: str | None = None
    category_id: str | None = None
    status: TaskStatus | None = None
    assignee: Assignee | None = None
    change_summary: str | None = None
    # Explicit null handling: fields listed here are set to NULL
    clear: list[str] = Field(default_factory=list)


class TaskOut(ORMModel):
    id: str
    title: str
    description: str | None
    due_at: str | None
    category_id: str | None
    category_name: str | None = None
    status: str
    assignee: str
    is_deleted: bool
    created_at: str
    updated_at: str
    ai_activity: str | None = None  # e.g. 調査中 / 資料作成中 / レビュー中 / 確認待ち
    pending_artifacts: int = 0
    active_plan_id: str | None = None
    open_chats: int = 0


class TaskListOut(BaseModel):
    items: list[TaskOut]
    total: int
    limit: int
    offset: int


class TaskVersionOut(ORMModel):
    id: str
    task_id: str
    version: int
    title: str
    description: str | None
    revised_content: dict[str, Any]
    previous_content: dict[str, Any] | None
    changed_by: str
    change_summary: str | None
    created_at: str


class TaskRevert(BaseModel):
    version: int


class TaskContextCreate(BaseModel):
    context: str = Field(min_length=1)
    source: str | None = None


class TaskContextOut(ORMModel):
    id: str
    task_id: str
    context: str
    source: str | None
    status: str
    created_at: str


class ApproveRequest(BaseModel):
    comment: str | None = None


class RevisionRequest(BaseModel):
    instructions: str = Field(min_length=1)
    kind: str = "revision"  # revision | additional_research | hold
