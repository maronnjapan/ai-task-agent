from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import ORMModel


class NotificationOut(ORMModel):
    id: str
    title: str
    body: str
    level: str
    status: str
    channel: str
    task_id: str | None
    source: str
    created_at: str
    read_at: str | None


class NotificationMarkRead(BaseModel):
    ids: list[str] | None = None  # None -> all


class ApprovalOut(ORMModel):
    id: str
    kind: str
    connection_id: str | None
    tool_name: str
    arguments: dict
    task_id: str | None
    work_item_id: str | None
    reason: str | None
    status: str
    result: str | None
    created_at: str
    resolved_at: str | None


class ApprovalDecision(BaseModel):
    approve: bool
    comment: str | None = None


class AuditEventOut(ORMModel):
    id: str
    event_type: str
    entity_type: str | None
    entity_id: str | None
    actor: str
    details: dict | None
    created_at: str


class ScheduledActionOut(ORMModel):
    id: str
    task_id: str | None
    execution_plan_id: str | None
    action_type: str
    payload: dict | None
    scheduled_at: str
    status: str
    created_at: str
    executed_at: str | None
