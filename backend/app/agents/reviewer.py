"""Review AI (SPEC 7.3, 12)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import AgentRunnerBase
from app.agents.context import AgentContext, clip
from app.agents.prompts.reviewer import REVIEW_SYSTEM_PROMPT
from app.agents.tools.review_tools import build_review_tools
from app.agents.tools.worker_tools import _artifact_service
from app.services.execution_service import ExecutionService
from app.services.task_service import TaskService
from app.utils import dumps

log = logging.getLogger(__name__)


@dataclass
class ReviewResult:
    status: str
    feedback: str
    task_results: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""


class ReviewAgent(AgentRunnerBase):
    agent_type = "review"
    max_iterations = 12

    def system_prompt(self) -> str:
        config = self.llm_config()
        prompt = REVIEW_SYSTEM_PROMPT
        if config.custom_prompt:
            prompt += "\n\n## 追加のシステム指示\n" + config.custom_prompt
        return prompt

    def build_context(self, ctx: AgentContext) -> dict[str, Any]:
        with self.app.db.session() as session:
            exec_service = ExecutionService(session)
            plan = exec_service.get_plan(ctx.plan_id)
            tasks = []
            for link in plan.task_links:
                task = TaskService(session).get(link.task_id)
                tasks.append(
                    {
                        "task_id": task.id,
                        "title": task.title,
                        "description": clip(task.description, 400),
                        "acceptance_criteria": link.acceptance_criteria,
                    }
                )
            artifacts = []
            service = _artifact_service(ctx, session)
            for artifact in service.list_for_plan(plan.id):
                artifacts.append(
                    {
                        "id": artifact.id,
                        "title": artifact.title,
                        "version": artifact.version,
                        "task_id": artifact.task_id,
                        "content_preview": clip(service.read_content(artifact.id), 6000),
                        "sources": [s.reference for s in artifact.sources],
                    }
                )
            return {
                "plan": {
                    "id": plan.id,
                    "objective": plan.objective,
                    "acceptance_criteria": plan.acceptance_criteria,
                    "replanning_attempt": plan.replanning_attempt,
                },
                "tasks": tasks,
                "work_item_results": exec_service.work_item_results(plan.id),
                "artifacts": artifacts,
            }

    async def run(self, plan_id: str, run_id: str | None = None) -> ReviewResult:
        ctx = AgentContext(app=self.app, agent_type="review", run_id=run_id, plan_id=plan_id, mode="run")
        tools = build_review_tools(ctx)
        context = self.build_context(ctx)
        prompt = (
            "## レビュー対象\n"
            + dumps(context)
            + "\n\n完了条件への達成度をタスクごとに評価し、submit_review を呼んでください。"
        )
        outcome = await self.invoke(self.system_prompt(), prompt, tools)
        recorded = ctx.recorder.get("review")
        if not recorded:
            return ReviewResult(
                status="failed",
                feedback="Review AI did not submit a verdict: " + clip(outcome.text, 500),
                task_results=[],
                text=outcome.text,
            )
        return ReviewResult(
            status=recorded["status"],
            feedback=recorded.get("feedback", ""),
            task_results=list(recorded.get("task_results") or []),
            text=outcome.text,
        )
