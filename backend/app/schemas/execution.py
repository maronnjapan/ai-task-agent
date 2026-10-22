from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class PlanTaskLinkOut(ORMModel):
    task_id: str
    execution_plan_id: str
    acceptance_criteria: str | None
    task_title: str | None = None


class ExecutionPlanOut(ORMModel):
    id: str
    parent_plan_id: str | None
    objective: str
    acceptance_criteria: str
    status: str
    replanning_attempt: int
    created_at: str
    updated_at: str
    task_links: list[PlanTaskLinkOut] = Field(default_factory=list)
    work_item_count: int = 0


class WorkItemOut(ORMModel):
    id: str
    execution_plan_id: str
    title: str
    description: str
    status: str
    result: dict[str, Any] | None
    order_index: int
    retry_count: int
    depends_on: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ReviewTaskResultOut(ORMModel):
    task_id: str
    status: str
    feedback: str | None


class ReviewOut(ORMModel):
    id: str
    execution_plan_id: str
    agent_run_id: str
    status: str
    feedback: str
    created_at: str
    task_results: list[ReviewTaskResultOut] = Field(default_factory=list)


class AgentRunOut(ORMModel):
    id: str
    execution_plan_id: str | None
    work_item_id: str | None
    agent_type: str
    status: str
    model: str | None
    trigger: str | None
    input_summary: str | None
    result_summary: str | None
    started_at: str
    finished_at: str | None
    error_message: str | None


class ManagerStatusOut(BaseModel):
    state: str  # idle | running | paused | disabled
    activity: str | None = None
    current_run_id: str | None = None
    last_run_at: str | None = None
    last_result: str | None = None
    next_scheduled_at: str | None = None
    pending_review_count: int = 0
    active_plan_count: int = 0
    queued_events: int = 0
    llm_ready: bool = True
    llm_issue: str | None = None
    consecutive_no_progress: int = 0
