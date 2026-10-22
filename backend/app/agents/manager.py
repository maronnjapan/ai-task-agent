"""Manager AI (SPEC 7.1, 8.5, 21)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import AgentOutcome, AgentRunnerBase
from app.agents.context import AgentContext, clip
from app.agents.prompts.manager import MANAGER_INSTRUCTION_PROMPT, MANAGER_REPLAN_PROMPT, MANAGER_SYSTEM_PROMPT
from app.agents.tools.manager_tools import build_manager_tools
from app.orchestrator.scheduler import SchedulerService
from app.services.chat_service import DecisionService
from app.services.execution_service import ExecutionService
from app.services.memory_service import MemoryService
from app.services.notification_service import NotificationService
from app.services.settings_service import SettingsService
from app.services.task_service import TaskService
from app.services.user_state_service import UserStateService
from app.utils import dumps, loads, now_iso

log = logging.getLogger(__name__)


@dataclass
class ManagerResult:
    text: str
    plan_ids: list[str] = field(default_factory=list)
    created_task_ids: list[str] = field(default_factory=list)
    updated_task_ids: list[str] = field(default_factory=list)
    notification_ids: list[str] = field(default_factory=list)
    scheduled_ids: list[str] = field(default_factory=list)
    decision_ids: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def made_progress(self) -> bool:
        return bool(self.plan_ids or self.created_task_ids or self.updated_task_ids or self.decision_ids)


class ManagerAgent(AgentRunnerBase):
    agent_type = "manager"
    max_iterations = 14

    def build_context(self, mode: str, instruction: str | None = None, replan_plan_id: str | None = None, trigger: str | None = None) -> str:
        """Collect the Manager's context from SQLite (SPEC 8.5)."""
        with self.app.db.session() as session:
            settings = SettingsService(session, self.app.settings)
            manager = settings.get_manager()
            task_service = TaskService(session)
            exec_service = ExecutionService(session)
            tasks, _ = task_service.list(include_completed=False, limit=300)
            task_rows = []
            for task in tasks:
                extra = task_service.decorate(task)
                task_rows.append(
                    {
                        "id": task.id,
                        "title": task.title,
                        "description": clip(task.description, 400),
                        "status": task.status,
                        "assignee": task.assignee,
                        "due_at": task.due_at,
                        "category": task.category.name if task.category else None,
                        "category_id": task.category_id,
                        "active_plan_id": extra["active_plan_id"],
                        "pending_artifacts": extra["pending_artifacts"],
                        "open_user_contexts": [c.context for c in task_service.open_contexts(task.id)],
                        "decisions": [d.content for d in DecisionService(session).active(task.id)][:5],
                    }
                )
            plans = []
            for plan in exec_service.active_plans():
                plans.append({"id": plan.id, "status": plan.status, "objective": plan.objective, "tasks": [l.task_id for l in plan.task_links], "progress": exec_service.plan_progress(plan.id)})
            recent_failed = []
            failed_plans, _ = exec_service.list_plans(status="failed,blocked", limit=5)
            for plan in failed_plans:
                review = exec_service.latest_review(plan.id)
                recent_failed.append({"id": plan.id, "status": plan.status, "objective": plan.objective, "attempt": plan.replanning_attempt, "feedback": clip(review.feedback if review else "", 600)})
            memories = [{"scope": m.scope, "kind": m.kind, "content": clip(m.content, 300)} for m in MemoryService(session).global_memories(limit=15)]
            user_state = UserStateService(session)
            state = user_state.get()
            notifications = NotificationService(session).recent_summary(hours=24, limit=8)
            scheduled = [{"id": a.id, "type": a.action_type, "at": a.scheduled_at, "task_id": a.task_id} for a in SchedulerService(session).pending()[:10]]
            replan_block = None
            if replan_plan_id:
                plan = exec_service.get_plan(replan_plan_id)
                review = exec_service.latest_review(plan.id)
                replan_block = {
                    "failed_plan": {"id": plan.id, "objective": plan.objective, "acceptance_criteria": plan.acceptance_criteria, "attempt": plan.replanning_attempt, "tasks": [{"task_id": l.task_id, "acceptance_criteria": l.acceptance_criteria} for l in plan.task_links]},
                    "work_item_results": exec_service.work_item_results(plan.id),
                    "review": {"status": review.status, "feedback": review.feedback, "task_results": [{"task_id": r.task_id, "status": r.status, "feedback": r.feedback} for r in review.task_results]} if review else None,
                    "max_replanning_attempts": manager.max_replanning_attempts,
                }
            context = {
                "now": now_iso(),
                "trigger": trigger,
                "mode": mode,
                "manager_settings": {"autonomy_level": manager.autonomy_level, "reminder_aggressiveness": manager.reminder_aggressiveness, "reevaluation_interval_minutes": manager.reevaluation_interval_minutes},
                "user_state": {"condition": state.condition or None, "active": user_state.is_active(state), "source": state.source},
                "tasks": task_rows,
                "active_plans": plans,
                "recent_failed_or_blocked_plans": recent_failed,
                "global_memories": memories,
                "recent_notifications": notifications,
                "scheduled_actions": scheduled,
            }
            custom_prompt = manager.custom_prompt
        parts = []
        if custom_prompt:
            parts.append("## ユーザーのカスタム指示\n" + custom_prompt)
        if mode == "replan":
            parts.append(MANAGER_REPLAN_PROMPT)
            parts.append("## 再計画の対象\n" + dumps(replan_block))
        if mode == "instruction":
            parts.append(MANAGER_INSTRUCTION_PROMPT)
            parts.append("## ユーザーの指示\n" + (instruction or ""))
        parts.append("## 現在の状況\n" + dumps(context))
        parts.append("上記を踏まえて判断し、必要なツールを呼び出してください。")
        return "\n\n".join(parts)

    def system_prompt(self) -> str:
        config = self.llm_config()
        prompt = MANAGER_SYSTEM_PROMPT
        if config.custom_prompt:
            prompt += "\n\n## 追加のシステム指示\n" + config.custom_prompt
        return prompt

    async def run(self, mode: str = "evaluate", trigger: str | None = None, instruction: str | None = None, replan_plan_id: str | None = None, run_id: str | None = None) -> ManagerResult:
        ctx = AgentContext(app=self.app, agent_type="manager", run_id=run_id, plan_id=replan_plan_id, mode=mode)
        tools = build_manager_tools(ctx)
        prompt = self.build_context(mode, instruction=instruction, replan_plan_id=replan_plan_id, trigger=trigger)
        outcome: AgentOutcome = await self.invoke(self.system_prompt(), prompt, tools)
        return ManagerResult(
            text=outcome.text,
            plan_ids=ctx.recorded("plans"),
            created_task_ids=ctx.recorded("created_tasks"),
            updated_task_ids=ctx.recorded("updated_tasks"),
            notification_ids=ctx.recorded("notifications"),
            scheduled_ids=ctx.recorded("scheduled"),
            decision_ids=ctx.recorded("decisions"),
            tool_calls=outcome.tool_calls,
        )


def summarize_result(result: ManagerResult) -> str:
    bits = []
    if result.plan_ids:
        bits.append(f"plans={len(result.plan_ids)}")
    if result.created_task_ids:
        bits.append(f"created_tasks={len(result.created_task_ids)}")
    if result.updated_task_ids:
        bits.append(f"updated_tasks={len(result.updated_task_ids)}")
    if result.notification_ids:
        bits.append(f"notifications={len(result.notification_ids)}")
    if result.scheduled_ids:
        bits.append(f"scheduled={len(result.scheduled_ids)}")
    summary = ", ".join(bits) if bits else "no changes"
    text = loads(result.text, None)
    return f"{summary}; {clip(result.text if text is None else dumps(text), 500)}"
