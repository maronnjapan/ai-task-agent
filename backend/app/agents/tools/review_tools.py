"""Review AI tools (SPEC 26.3)."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool

from app.agents.context import AgentContext, clip
from app.agents.tools.common import as_json, make_tool, task_to_dict
from app.agents.tools.worker_tools import _artifact_service
from app.services.chat_service import DecisionService
from app.services.errors import ServiceError
from app.services.execution_service import ExecutionService
from app.services.task_service import TaskService


def build_review_tools(ctx: AgentContext) -> list[BaseTool]:
    def get_execution_plan() -> str:
        """The plan under review: objective, acceptance criteria, tasks with their own criteria and decisions."""
        with ctx.session() as session:
            service = ExecutionService(session)
            plan = service.get_plan(ctx.plan_id)
            tasks = []
            for link in plan.task_links:
                try:
                    task = TaskService(session).get(link.task_id)
                except ServiceError:
                    continue
                tasks.append(task_to_dict(task, {"acceptance_criteria": link.acceptance_criteria, "decisions": [d.content for d in DecisionService(session).active(task.id)]}))
            return as_json({"id": plan.id, "objective": plan.objective, "acceptance_criteria": plan.acceptance_criteria, "replanning_attempt": plan.replanning_attempt, "parent_plan_id": plan.parent_plan_id, "tasks": tasks})

    def get_work_item_results() -> str:
        """All work items of the plan with their reported results (dependency order)."""
        with ctx.session() as session:
            return as_json(ExecutionService(session).work_item_results(ctx.plan_id))

    def read_artifact(artifact_id: str, version: int | None = None) -> str:
        """Read an artifact produced by the plan."""
        with ctx.session() as session:
            service = _artifact_service(ctx, session)
            try:
                artifact = service.get(artifact_id)
                content = service.read_content(artifact_id, version)
            except ServiceError as exc:
                return f"error: {exc.message}"
            return as_json({"id": artifact.id, "title": artifact.title, "version": version or artifact.version, "content": clip(content, 20_000)})

    def get_source_references(artifact_id: str | None = None) -> str:
        """Sources (citations) recorded for the plan's artifacts, optionally for one artifact."""
        with ctx.session() as session:
            service = _artifact_service(ctx, session)
            artifacts = [service.get(artifact_id)] if artifact_id else service.list_for_plan(ctx.plan_id)
            rows: list[dict[str, Any]] = []
            for artifact in artifacts:
                rows.append({"artifact_id": artifact.id, "title": artifact.title, "sources": [{"title": s.title, "reference": s.reference, "type": s.source_type} for s in artifact.sources]})
            return as_json(rows)

    def submit_review(status: str, feedback: str, task_results: list[dict[str, Any]] | None = None) -> str:
        """Submit the verdict (status: passed | failed | blocked). task_results: [{"task_id", "status", "feedback"}] for each task."""
        if status not in ("passed", "failed", "blocked"):
            return "error: status must be passed, failed or blocked"
        ctx.recorder["review"] = {"status": status, "feedback": feedback, "task_results": task_results or []}
        return "recorded"

    return [
        make_tool(get_execution_plan, "get_execution_plan", get_execution_plan.__doc__ or ""),
        make_tool(get_work_item_results, "get_work_item_results", get_work_item_results.__doc__ or ""),
        make_tool(read_artifact, "read_artifact", read_artifact.__doc__ or ""),
        make_tool(get_source_references, "get_source_references", get_source_references.__doc__ or ""),
        make_tool(submit_review, "submit_review", submit_review.__doc__ or ""),
    ]
