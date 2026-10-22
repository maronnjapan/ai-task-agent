"""Manager AI tools (SPEC 26.1)."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool

from app.agents.context import AgentContext
from app.agents.tools.common import as_json, make_tool, memory_to_dict, plan_to_dict, task_to_dict
from app.models.enums import Assignee, TaskStatus
from app.schemas.memories import MemoryCreate
from app.schemas.tasks import TaskCreate, TaskUpdate
from app.services.chat_service import DecisionService
from app.services.errors import ServiceError
from app.services.execution_service import ExecutionService
from app.services.memory_service import MemoryService
from app.services.notification_service import NotificationService
from app.services.settings_service import SettingsService
from app.services.task_service import TaskService
from app.services.user_state_service import UserStateService
from app.utils import iso_in, parse_iso


def build_manager_tools(ctx: AgentContext) -> list[BaseTool]:
    app = ctx.app

    def list_tasks(status: str | None = None, include_completed: bool = False) -> str:
        """List tasks. ``status`` may be a comma separated list (todo,in_progress,review_pending,blocked,completed)."""
        with ctx.session() as session:
            service = TaskService(session, app.broker)
            tasks, _ = service.list(status=status, include_completed=include_completed, limit=500)
            rows = []
            for task in tasks:
                extra = service.decorate(task)
                open_contexts = [c.context for c in service.open_contexts(task.id)]
                rows.append(task_to_dict(task, {"active_plan_id": extra["active_plan_id"], "open_user_contexts": open_contexts}))
            return as_json(rows)

    def get_task(task_id: str) -> str:
        """Get one task with its decisions, open user contexts and recent plans."""
        with ctx.session() as session:
            service = TaskService(session, app.broker)
            try:
                task = service.get(task_id)
            except ServiceError as exc:
                return f"error: {exc.message}"
            decisions = [d.content for d in DecisionService(session).active(task.id)]
            contexts = [{"context": c.context, "source": c.source} for c in service.open_contexts(task.id)]
            plans = [
                {"id": p.id, "status": p.status, "objective": p.objective, "replanning_attempt": p.replanning_attempt}
                for p in ExecutionService(session).plans_for_task(task.id)[:5]
            ]
            return as_json(task_to_dict(task, {"decisions": decisions, "open_user_contexts": contexts, "plans": plans}))

    def create_task(title: str, description: str | None = None, due_at: str | None = None, category_id: str | None = None, assignee: str = "shared") -> str:
        """Create a new task (assignee: user | ai | shared). due_at is an ISO-8601 datetime or null."""
        with ctx.session() as session:
            try:
                task = TaskService(session, app.broker).create(
                    TaskCreate(title=title, description=description, due_at=due_at, category_id=category_id, assignee=Assignee(assignee)),
                    actor="ai",
                    change_summary="Manager AI が作成",
                )
            except (ServiceError, ValueError) as exc:
                return f"error: {exc}"
            ctx.record("created_tasks", task.id)
            return as_json(task_to_dict(task))

    def update_task(task_id: str, title: str | None = None, description: str | None = None, due_at: str | None = None, status: str | None = None, assignee: str | None = None, category_id: str | None = None, change_summary: str | None = None) -> str:
        """Update task fields. Only provided fields change. Status cannot be set to completed (user approval required)."""
        if status == "completed":
            return "error: completed requires user approval; use review flow instead"
        with ctx.session() as session:
            try:
                patch = TaskUpdate(
                    title=title,
                    description=description,
                    due_at=due_at,
                    status=TaskStatus(status) if status else None,
                    assignee=Assignee(assignee) if assignee else None,
                    category_id=category_id,
                    change_summary=change_summary or "Manager AI が更新",
                )
                patch = TaskUpdate.model_validate(patch.model_dump(exclude_none=True))
                task = TaskService(session, app.broker).update(task_id, patch, actor="ai")
            except (ServiceError, ValueError) as exc:
                return f"error: {exc}"
            ctx.record("updated_tasks", task.id)
            return as_json(task_to_dict(task))

    def get_task_decisions(task_id: str) -> str:
        """Formal decisions for a task (active ones first)."""
        with ctx.session() as session:
            rows = DecisionService(session).list(task_id)
            return as_json([{"id": d.id, "content": d.content, "status": d.status, "decided_at": d.decided_at} for d in rows])

    def get_relevant_memories(query: str | None = None, task_id: str | None = None, limit: int = 15) -> str:
        """Search long-term memory. With task_id returns global + category + task memories for that task."""
        with ctx.session() as session:
            service = MemoryService(session)
            if task_id:
                try:
                    task = TaskService(session).get(task_id)
                except ServiceError as exc:
                    return f"error: {exc.message}"
                rows = service.relevant_for_task(task, query=query, limit=limit)
            elif query:
                rows = service.search(query, limit=limit)
            else:
                rows = service.global_memories(limit=limit)
            return as_json([memory_to_dict(m) for m in rows])

    def get_user_state() -> str:
        """Current user condition (e.g. tired, busy) with source and expiry."""
        with ctx.session() as session:
            service = UserStateService(session)
            state = service.get()
            return as_json({"condition": state.condition or None, "active": service.is_active(state), "source": state.source, "expires_at": state.expires_at})

    def list_execution_plans(status: str | None = None, task_id: str | None = None) -> str:
        """List execution plans (optionally filtered by status list or task)."""
        with ctx.session() as session:
            service = ExecutionService(session)
            plans, _ = service.list_plans(status=status, task_id=task_id, limit=50)
            return as_json([plan_to_dict(p, service, include_items=False) for p in plans])

    def get_execution_plan(plan_id: str) -> str:
        """Get a plan with its work items, results and latest review."""
        with ctx.session() as session:
            service = ExecutionService(session)
            try:
                plan = service.get_plan(plan_id)
            except ServiceError as exc:
                return f"error: {exc.message}"
            data = plan_to_dict(plan, service)
            review = service.latest_review(plan.id)
            if review:
                data["latest_review"] = {
                    "status": review.status,
                    "feedback": review.feedback,
                    "task_results": [{"task_id": r.task_id, "status": r.status, "feedback": r.feedback} for r in review.task_results],
                }
            return as_json(data)

    def create_execution_plan(objective: str, acceptance_criteria: str, task_ids: list[str], task_acceptance_criteria: dict[str, str] | None = None, parent_plan_id: str | None = None) -> str:
        """Create an Execution Plan for one or more tasks. task_acceptance_criteria maps task_id -> criteria.
        For replanning pass parent_plan_id of the failed plan."""
        with ctx.session() as session:
            service = ExecutionService(session, app.broker)
            task_service = TaskService(session, app.broker)
            if ctx.mode == "replan" and not parent_plan_id:
                parent_plan_id = ctx.plan_id
            if ctx.mode == "evaluate" and len(ctx.recorded("plans")) >= _plan_limit(session, app):
                return "error: plan limit for this cycle reached"
            for task_id in task_ids:
                try:
                    task = task_service.get(task_id)
                except ServiceError as exc:
                    return f"error: {exc.message}"
                if task.status in (TaskStatus.COMPLETED, TaskStatus.REVIEW_PENDING):
                    return f"error: task {task_id} is {task.status}; it must not be planned"
                if task.assignee == Assignee.USER:
                    return f"error: task {task_id} is assigned to the user; AI must not work on it"
                active = [p for p in service.plans_for_task(task_id) if p.status in ("planned", "running", "reviewing") and p.id != parent_plan_id]
                if active:
                    return f"error: task {task_id} already has an active plan {active[0].id}"
            try:
                plan = service.create_plan(
                    objective=objective,
                    acceptance_criteria=acceptance_criteria,
                    task_ids=task_ids,
                    task_acceptance=task_acceptance_criteria,
                    parent_plan_id=parent_plan_id,
                    created_by_run_id=ctx.run_id,
                )
            except ServiceError as exc:
                return f"error: {exc.message}"
            for task_id in task_ids:
                task = task_service.get(task_id)
                if task.status in (TaskStatus.TODO, TaskStatus.BLOCKED):
                    task_service.set_status(task_id, TaskStatus.IN_PROGRESS, actor="ai", summary="Manager AI が計画を作成")
            ctx.record("plans", plan.id)
            return as_json({"plan_id": plan.id, "status": plan.status, "tasks": task_ids})

    def create_work_items(plan_id: str, items: list[dict[str, Any]]) -> str:
        """Add work items to a plan. Each item: {"title": str, "description": str, "depends_on": [index or title of other items]}.
        Dependencies must stay within the plan and must not form cycles."""
        with ctx.session() as session:
            service = ExecutionService(session, app.broker)
            try:
                created = service.create_work_items(plan_id, items)
            except ServiceError as exc:
                return f"error: {exc.message}"
            ctx.record("work_items", [w.id for w in created])
            deps = service.dependencies(plan_id)
            return as_json([{"id": w.id, "title": w.title, "depends_on": sorted(deps.get(w.id, ()))} for w in created])

    def get_review_results(plan_id: str) -> str:
        """Review results for a plan (latest first)."""
        with ctx.session() as session:
            service = ExecutionService(session)
            try:
                reviews = service.list_reviews(plan_id)
            except ServiceError as exc:
                return f"error: {exc.message}"
            return as_json(
                [
                    {
                        "id": r.id,
                        "status": r.status,
                        "feedback": r.feedback,
                        "created_at": r.created_at,
                        "task_results": [{"task_id": t.task_id, "status": t.status, "feedback": t.feedback} for t in r.task_results],
                    }
                    for r in reviews
                ]
            )

    def schedule_action(action_type: str, scheduled_at: str | None = None, delay_minutes: int | None = None, task_id: str | None = None, note: str | None = None) -> str:
        """Schedule a future action: manager_reevaluate | due_check | notify | remind_pending_review.
        Provide scheduled_at (ISO-8601) or delay_minutes."""
        from app.orchestrator.scheduler import SchedulerService

        if scheduled_at is None and delay_minutes is None:
            return "error: scheduled_at or delay_minutes is required"
        when = scheduled_at or iso_in(minutes=max(1, int(delay_minutes or 1)))
        try:
            parse_iso(when)
        except ValueError:
            return "error: scheduled_at must be ISO-8601"
        with ctx.session() as session:
            action = SchedulerService(session).schedule(action_type, when, task_id=task_id, payload={"note": note, "by": "manager"})
            ctx.record("scheduled", action.id)
            return as_json({"id": action.id, "action_type": action.action_type, "scheduled_at": action.scheduled_at})

    def create_notification(title: str, body: str = "", level: str = "normal", task_id: str | None = None) -> str:
        """Notify the user (level: low | normal | high). Duplicate or too frequent notifications are suppressed."""
        with ctx.session() as session:
            settings = SettingsService(session, app.settings).get_notifications()
            service = NotificationService(session, settings, app.platform, app.broker)
            try:
                row = service.create(title, body, level=level, task_id=task_id, source="manager", dedupe_key=f"manager:{task_id or 'global'}:{title[:40]}")
            except ValueError as exc:
                return f"error: {exc}"
            if row is None:
                return "suppressed: a similar notification was sent recently"
            ctx.record("notifications", row.id)
            return as_json({"id": row.id, "title": row.title})

    def record_decision(task_id: str, content: str) -> str:
        """Record a formal decision the user explicitly stated in their instruction. Never record assumptions."""
        if ctx.mode != "instruction":
            return "error: decisions can only be recorded from an explicit user instruction"
        with ctx.session() as session:
            try:
                decision = DecisionService(session, app.broker).record(task_id, content, actor="user")
            except ServiceError as exc:
                return f"error: {exc.message}"
            ctx.record("decisions", decision.id)
            return as_json({"id": decision.id, "content": decision.content})

    def save_memory(content: str, scope: str = "global", task_id: str | None = None, category_id: str | None = None, kind: str = "ai_inference") -> str:
        """Save a long-term memory (kind: hypothesis | ai_inference | research | decision). Decision kind only for confirmed facts."""
        with ctx.session() as session:
            try:
                memory = MemoryService(session).create(
                    MemoryCreate(scope=scope, task_id=task_id, category_id=category_id, content=content, source="manager", kind=kind, confirmed=kind == "decision" and ctx.mode == "instruction"),
                    actor="ai",
                )
            except (ServiceError, ValueError) as exc:
                return f"error: {exc}"
            ctx.record("memories", memory.id)
            return as_json({"id": memory.id})

    tools = [
        make_tool(list_tasks, "list_tasks", list_tasks.__doc__ or ""),
        make_tool(get_task, "get_task", get_task.__doc__ or ""),
        make_tool(create_task, "create_task", create_task.__doc__ or ""),
        make_tool(update_task, "update_task", update_task.__doc__ or ""),
        make_tool(get_task_decisions, "get_task_decisions", get_task_decisions.__doc__ or ""),
        make_tool(get_relevant_memories, "get_relevant_memories", get_relevant_memories.__doc__ or ""),
        make_tool(get_user_state, "get_user_state", get_user_state.__doc__ or ""),
        make_tool(list_execution_plans, "list_execution_plans", list_execution_plans.__doc__ or ""),
        make_tool(get_execution_plan, "get_execution_plan", get_execution_plan.__doc__ or ""),
        make_tool(create_execution_plan, "create_execution_plan", create_execution_plan.__doc__ or ""),
        make_tool(create_work_items, "create_work_items", create_work_items.__doc__ or ""),
        make_tool(get_review_results, "get_review_results", get_review_results.__doc__ or ""),
        make_tool(schedule_action, "schedule_action", schedule_action.__doc__ or ""),
        make_tool(create_notification, "create_notification", create_notification.__doc__ or ""),
        make_tool(record_decision, "record_decision", record_decision.__doc__ or ""),
        make_tool(save_memory, "save_memory", save_memory.__doc__ or ""),
    ]
    return tools


def _plan_limit(session, app) -> int:
    manager = SettingsService(session, app.settings).get_manager()
    return {"conservative": 1, "balanced": 3, "proactive": 5}.get(manager.autonomy_level, 3)
