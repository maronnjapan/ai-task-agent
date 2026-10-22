"""Execution plans, work items, dependencies, agent runs and reviews (SPEC 10-12)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from app.infrastructure.events import EventBroker
from app.models import (
    AgentRun,
    ExecutionPlan,
    RelatedPlanToTask,
    Review,
    ReviewTaskResult,
    Task,
    WorkItem,
    WorkItemDependency,
)
from app.models.enums import PlanStatus, ReviewStatus, RunStatus, WorkItemStatus
from app.services.audit_service import AuditService
from app.services.errors import NotFoundError, ValidationError
from app.utils import dumps, loads, now_iso

ACTIVE_PLAN_STATUSES = (PlanStatus.PLANNED, PlanStatus.RUNNING, PlanStatus.REVIEWING)


class CycleError(ValidationError):
    pass


def detect_cycle(edges: dict[str, set[str]]) -> list[str] | None:
    """Return a cycle path if the dependency graph has one (SPEC 11.3)."""
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(int)
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        color[node] = GREY
        stack.append(node)
        for nxt in edges.get(node, ()):
            if color[nxt] == GREY:
                return stack[stack.index(nxt) :] + [nxt]
            if color[nxt] == WHITE:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in list(edges):
        if color[node] == WHITE:
            found = visit(node)
            if found:
                return found
    return None


def topological_order(items: list[WorkItem], deps: dict[str, set[str]]) -> list[WorkItem]:
    """Stable topological sort: dependencies first, ties broken by order_index."""
    by_id = {item.id: item for item in items}
    indegree = {item.id: 0 for item in items}
    dependents: dict[str, list[str]] = defaultdict(list)
    for item_id, prereqs in deps.items():
        for prereq in prereqs:
            if prereq in by_id and item_id in by_id:
                indegree[item_id] += 1
                dependents[prereq].append(item_id)
    ready = sorted(
        [i for i, d in indegree.items() if d == 0], key=lambda i: (by_id[i].order_index, by_id[i].created_at)
    )
    ordered: list[WorkItem] = []
    while ready:
        current = ready.pop(0)
        ordered.append(by_id[current])
        for dep in dependents[current]:
            indegree[dep] -= 1
            if indegree[dep] == 0:
                ready.append(dep)
                ready.sort(key=lambda i: (by_id[i].order_index, by_id[i].created_at))
    if len(ordered) != len(items):
        raise CycleError("Work item dependencies contain a cycle")
    return ordered


class ExecutionService:
    def __init__(self, session: Session, broker: EventBroker | None = None):
        self.session = session
        self.broker = broker
        self.audit = AuditService(session)

    # --- plans --------------------------------------------------------
    def get_plan(self, plan_id: str) -> ExecutionPlan:
        plan = self.session.get(ExecutionPlan, plan_id)
        if plan is None:
            raise NotFoundError("Execution plan not found")
        return plan

    def list_plans(
        self, status: str | None = None, task_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[ExecutionPlan], int]:
        stmt = select(ExecutionPlan)
        if status:
            stmt = stmt.where(ExecutionPlan.status.in_([s for s in status.split(",") if s]))
        if task_id:
            stmt = stmt.join(
                RelatedPlanToTask, RelatedPlanToTask.execution_plan_id == ExecutionPlan.id
            ).where(RelatedPlanToTask.task_id == task_id)
        total = self.session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        rows = (
            self.session.execute(stmt.order_by(ExecutionPlan.created_at.desc()).limit(limit).offset(offset))
            .scalars()
            .all()
        )
        return list(rows), int(total)

    def active_plans(self) -> list[ExecutionPlan]:
        return list(
            self.session.execute(
                select(ExecutionPlan)
                .where(ExecutionPlan.status.in_([str(s) for s in ACTIVE_PLAN_STATUSES]))
                .order_by(ExecutionPlan.created_at)
            ).scalars()
        )

    def plans_for_task(self, task_id: str) -> list[ExecutionPlan]:
        rows, _ = self.list_plans(task_id=task_id, limit=100)
        return rows

    def create_plan(
        self,
        objective: str,
        acceptance_criteria: str,
        task_ids: list[str],
        task_acceptance: dict[str, str] | None = None,
        parent_plan_id: str | None = None,
        created_by_run_id: str | None = None,
        actor: str = "ai",
    ) -> ExecutionPlan:
        objective = (objective or "").strip()
        if not objective:
            raise ValidationError("Objective is required")
        task_ids = list(dict.fromkeys(t for t in task_ids if t))
        if not task_ids:
            raise ValidationError("At least one task is required")
        for task_id in task_ids:
            task = self.session.get(Task, task_id)
            if task is None or task.is_deleted:
                raise NotFoundError(f"Task not found: {task_id}")
        attempt = 0
        if parent_plan_id:
            parent = self.get_plan(parent_plan_id)
            attempt = parent.replanning_attempt + 1
            if parent.status in [str(s) for s in ACTIVE_PLAN_STATUSES] or parent.status == PlanStatus.FAILED:
                parent.status = PlanStatus.REPLANNED
                parent.updated_at = now_iso()
            # Work that never ran in the superseded plan is skipped (SPEC 11.2).
            for item in self.list_work_items(parent.id):
                if item.status in (WorkItemStatus.PENDING, WorkItemStatus.BLOCKED):
                    item.status = WorkItemStatus.SKIPPED
                    item.result = dumps({"status": "skipped", "summary": "再計画により不要になりました"})
                    item.updated_at = now_iso()
        plan = ExecutionPlan(
            parent_plan_id=parent_plan_id,
            objective=objective,
            acceptance_criteria=acceptance_criteria or "",
            status=PlanStatus.PLANNED,
            replanning_attempt=attempt,
            created_by_run_id=created_by_run_id,
        )
        self.session.add(plan)
        self.session.flush()
        for task_id in task_ids:
            self.session.add(
                RelatedPlanToTask(
                    task_id=task_id,
                    execution_plan_id=plan.id,
                    acceptance_criteria=(task_acceptance or {}).get(task_id),
                )
            )
        self.session.flush()
        self.audit.record(
            "plan.created", "execution_plan", plan.id, actor, {"tasks": task_ids, "parent": parent_plan_id}
        )
        if self.broker:
            self.broker.publish(
                "plan.created", {"plan_id": plan.id, "task_ids": task_ids, "parent_plan_id": parent_plan_id}
            )
            if parent_plan_id:
                self.broker.publish(
                    "plan.updated", {"plan_id": parent_plan_id, "status": "replanned", "task_ids": task_ids}
                )
        return plan

    def set_plan_status(self, plan_id: str, status: str, actor: str = "system") -> ExecutionPlan:
        plan = self.get_plan(plan_id)
        plan.status = str(PlanStatus(status))
        plan.updated_at = now_iso()
        self.session.flush()
        self.audit.record("plan.status", "execution_plan", plan.id, actor, {"status": plan.status})
        if self.broker:
            self.broker.publish(
                "plan.updated",
                {
                    "plan_id": plan.id,
                    "status": plan.status,
                    "task_ids": [link.task_id for link in plan.task_links],
                },
            )
        return plan

    def plan_task_ids(self, plan_id: str) -> list[str]:
        return [row.task_id for row in self.get_plan(plan_id).task_links]

    def plan_chain(self, plan_id: str) -> list[ExecutionPlan]:
        """The plan and its replanning ancestors, oldest first."""
        chain: list[ExecutionPlan] = []
        current: ExecutionPlan | None = self.get_plan(plan_id)
        seen: set[str] = set()
        while current is not None and current.id not in seen:
            chain.append(current)
            seen.add(current.id)
            current = (
                self.session.get(ExecutionPlan, current.parent_plan_id) if current.parent_plan_id else None
            )
        chain.reverse()
        return chain

    # --- work items ---------------------------------------------------
    def get_work_item(self, work_item_id: str) -> WorkItem:
        item = self.session.get(WorkItem, work_item_id)
        if item is None:
            raise NotFoundError("Work item not found")
        return item

    def list_work_items(self, plan_id: str) -> list[WorkItem]:
        self.get_plan(plan_id)
        return list(
            self.session.execute(
                select(WorkItem)
                .where(WorkItem.execution_plan_id == plan_id)
                .order_by(WorkItem.order_index, WorkItem.created_at)
            ).scalars()
        )

    def dependencies(self, plan_id: str) -> dict[str, set[str]]:
        items = self.list_work_items(plan_id)
        ids = {item.id for item in items}
        deps: dict[str, set[str]] = {item.id: set() for item in items}
        if not ids:
            return deps
        rows = self.session.execute(
            select(WorkItemDependency).where(WorkItemDependency.work_item_id.in_(ids))
        ).scalars()
        for row in rows:
            deps[row.work_item_id].add(row.depends_on_work_item_id)
        return deps

    def create_work_items(
        self, plan_id: str, items: list[dict[str, Any]], actor: str = "ai"
    ) -> list[WorkItem]:
        """Create work items. ``depends_on`` may reference other items by index or title in the same batch,
        or by id for existing items of the plan."""
        plan = self.get_plan(plan_id)
        if not items:
            raise ValidationError("At least one work item is required")
        existing = self.list_work_items(plan_id)
        base_index = max([w.order_index for w in existing], default=-1) + 1
        created: list[WorkItem] = []
        for offset, spec in enumerate(items):
            description = str(spec.get("description") or "").strip()
            title = str(spec.get("title") or "").strip() or description[:80]
            if not description:
                raise ValidationError("Work item description is required")
            item = WorkItem(
                execution_plan_id=plan.id,
                title=title[:200],
                description=description,
                order_index=base_index + offset,
            )
            self.session.add(item)
            created.append(item)
        self.session.flush()
        by_title = {w.title: w.id for w in existing + created}
        by_id = {w.id for w in existing + created}
        edges: dict[str, set[str]] = self.dependencies(plan_id)
        for offset, spec in enumerate(items):
            item = created[offset]
            for ref in spec.get("depends_on") or []:
                target: str | None = None
                if isinstance(ref, int) and 0 <= ref < len(created):
                    target = created[ref].id
                elif isinstance(ref, str):
                    if ref in by_id:
                        target = ref
                    elif ref in by_title:
                        target = by_title[ref]
                    elif ref.isdigit() and int(ref) < len(created):
                        target = created[int(ref)].id
                if target is None or target == item.id:
                    continue
                edges.setdefault(item.id, set()).add(target)
        cycle = detect_cycle(edges)
        if cycle:
            raise CycleError("Work item dependencies contain a cycle: " + " -> ".join(cycle))
        for item in created:
            for target in edges.get(item.id, ()):
                self.session.add(WorkItemDependency(work_item_id=item.id, depends_on_work_item_id=target))
        self.session.flush()
        self.audit.record("work_items.created", "execution_plan", plan.id, actor, {"count": len(created)})
        if self.broker:
            self.broker.publish("work_items.created", {"plan_id": plan.id, "count": len(created)})
        return created

    def add_dependency(self, work_item_id: str, depends_on_id: str) -> None:
        item = self.get_work_item(work_item_id)
        dep = self.get_work_item(depends_on_id)
        if item.execution_plan_id != dep.execution_plan_id:
            raise ValidationError("Dependencies must stay within one execution plan")
        if item.id == dep.id:
            raise ValidationError("A work item cannot depend on itself")
        edges = self.dependencies(item.execution_plan_id)
        edges.setdefault(item.id, set()).add(dep.id)
        if detect_cycle(edges):
            raise CycleError("Adding this dependency would create a cycle")
        self.session.add(WorkItemDependency(work_item_id=item.id, depends_on_work_item_id=dep.id))
        self.session.flush()

    def ordered_work_items(self, plan_id: str) -> list[WorkItem]:
        return topological_order(self.list_work_items(plan_id), self.dependencies(plan_id))

    def next_runnable(self, plan_id: str) -> WorkItem | None:
        deps = self.dependencies(plan_id)
        items = self.ordered_work_items(plan_id)
        status = {item.id: item.status for item in items}
        for item in items:
            if item.status != WorkItemStatus.PENDING:
                continue
            if all(status.get(d) == WorkItemStatus.SUCCEEDED for d in deps.get(item.id, ())):
                return item
        return None

    def block_unrunnable(self, plan_id: str) -> list[WorkItem]:
        """Mark pending items whose prerequisites failed/blocked as blocked."""
        deps = self.dependencies(plan_id)
        items = self.list_work_items(plan_id)
        status = {item.id: item.status for item in items}
        blocked: list[WorkItem] = []
        changed = True
        while changed:
            changed = False
            for item in items:
                if status[item.id] != WorkItemStatus.PENDING:
                    continue
                if any(
                    status.get(d) in (WorkItemStatus.FAILED, WorkItemStatus.BLOCKED, WorkItemStatus.SKIPPED)
                    for d in deps.get(item.id, ())
                ):
                    item.status = WorkItemStatus.BLOCKED
                    item.result = dumps(
                        {
                            "status": "blocked",
                            "summary": "前提となる作業が失敗したため実行できません",
                            "blockers": ["dependency_failed"],
                        }
                    )
                    item.updated_at = now_iso()
                    status[item.id] = WorkItemStatus.BLOCKED
                    blocked.append(item)
                    changed = True
        self.session.flush()
        return blocked

    def set_work_item_status(
        self, work_item_id: str, status: str, result: dict[str, Any] | None = None
    ) -> WorkItem:
        item = self.get_work_item(work_item_id)
        item.status = str(WorkItemStatus(status))
        if result is not None:
            item.result = dumps(result)
        item.updated_at = now_iso()
        self.session.flush()
        if self.broker:
            self.broker.publish(
                "work_item.updated",
                {"work_item_id": item.id, "plan_id": item.execution_plan_id, "status": item.status},
            )
        return item

    def work_item_results(self, plan_id: str) -> list[dict[str, Any]]:
        results = []
        for item in self.ordered_work_items(plan_id):
            results.append(
                {
                    "work_item_id": item.id,
                    "title": item.title,
                    "description": item.description,
                    "status": item.status,
                    "result": loads(item.result, None),
                }
            )
        return results

    def plan_progress(self, plan_id: str) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for item in self.list_work_items(plan_id):
            counts[item.status] += 1
        counts["total"] = sum(v for k, v in counts.items() if k != "total")
        return dict(counts)

    # --- agent runs ---------------------------------------------------
    def start_run(
        self,
        agent_type: str,
        execution_plan_id: str | None = None,
        work_item_id: str | None = None,
        model: str | None = None,
        trigger: str | None = None,
        input_summary: str | None = None,
    ) -> AgentRun:
        run = AgentRun(
            agent_type=agent_type,
            execution_plan_id=execution_plan_id,
            work_item_id=work_item_id,
            model=model,
            trigger=trigger,
            input_summary=input_summary,
            status=RunStatus.RUNNING,
        )
        self.session.add(run)
        self.session.flush()
        self.audit.record(
            "agent_run.started",
            "agent_run",
            run.id,
            "ai",
            {"agent_type": agent_type, "model": model, "plan_id": execution_plan_id},
        )
        if self.broker:
            self.broker.publish(
                "agent_run.started",
                {
                    "run_id": run.id,
                    "agent_type": agent_type,
                    "plan_id": execution_plan_id,
                    "work_item_id": work_item_id,
                },
            )
        return run

    def finish_run(
        self, run_id: str, status: str, result_summary: str | None = None, error_message: str | None = None
    ) -> AgentRun:
        run = self.session.get(AgentRun, run_id)
        if run is None:
            raise NotFoundError("Agent run not found")
        run.status = str(RunStatus(status))
        run.result_summary = result_summary
        run.error_message = error_message
        run.finished_at = now_iso()
        self.session.flush()
        self.audit.record(
            "agent_run.finished", "agent_run", run.id, "ai", {"status": run.status, "error": error_message}
        )
        if self.broker:
            self.broker.publish(
                "agent_run.finished",
                {
                    "run_id": run.id,
                    "agent_type": run.agent_type,
                    "status": run.status,
                    "plan_id": run.execution_plan_id,
                },
            )
        return run

    def list_runs(
        self,
        plan_id: str | None = None,
        agent_type: str | None = None,
        task_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AgentRun], int]:
        stmt = select(AgentRun)
        if plan_id:
            stmt = stmt.where(AgentRun.execution_plan_id == plan_id)
        if agent_type:
            stmt = stmt.where(AgentRun.agent_type == agent_type)
        if task_id:
            plan_ids = select(RelatedPlanToTask.execution_plan_id).where(RelatedPlanToTask.task_id == task_id)
            stmt = stmt.where(AgentRun.execution_plan_id.in_(plan_ids))
        total = self.session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        rows = (
            self.session.execute(stmt.order_by(AgentRun.started_at.desc()).limit(limit).offset(offset))
            .scalars()
            .all()
        )
        return list(rows), int(total)

    def running_runs(self) -> list[AgentRun]:
        return list(
            self.session.execute(select(AgentRun).where(AgentRun.status == RunStatus.RUNNING)).scalars()
        )

    # --- reviews ------------------------------------------------------
    def record_review(
        self,
        plan_id: str,
        run_id: str,
        status: str,
        feedback: str,
        task_results: list[dict[str, Any]],
        strict: bool = True,
    ) -> Review:
        plan = self.get_plan(plan_id)
        plan_tasks = set(self.plan_task_ids(plan_id))
        status = str(ReviewStatus(status))
        review = Review(
            execution_plan_id=plan.id, agent_run_id=run_id, status=status, feedback=feedback or ""
        )
        self.session.add(review)
        self.session.flush()
        seen: set[str] = set()
        for entry in task_results:
            task_id = str(entry.get("task_id") or "")
            if task_id not in plan_tasks:
                if strict:
                    raise ValidationError(f"Review result references a task outside the plan: {task_id}")
                continue  # the reviewer referenced an unknown id; ignore it (SPEC 23.4 integrity)
            if task_id in seen:
                continue
            seen.add(task_id)
            try:
                task_status = str(ReviewStatus(str(entry.get("status", status)).lower()))
            except ValueError:
                task_status = status
            self.session.add(
                ReviewTaskResult(
                    review_id=review.id,
                    task_id=task_id,
                    status=task_status,
                    feedback=entry.get("feedback"),
                )
            )
        for task_id in plan_tasks - seen:
            self.session.add(
                ReviewTaskResult(review_id=review.id, task_id=task_id, status=status, feedback=None)
            )
        self.session.flush()
        self.audit.record(
            "review.recorded", "review", review.id, "ai", {"plan_id": plan_id, "status": status}
        )
        if self.broker:
            self.broker.publish(
                "review.recorded", {"review_id": review.id, "plan_id": plan_id, "status": status}
            )
        return review

    def list_reviews(self, plan_id: str) -> list[Review]:
        self.get_plan(plan_id)
        return list(
            self.session.execute(
                select(Review)
                .where(Review.execution_plan_id == plan_id)
                .order_by(Review.created_at.desc(), literal_column("rowid").desc())
            ).scalars()
        )

    def latest_review(self, plan_id: str) -> Review | None:
        reviews = self.list_reviews(plan_id)
        return reviews[0] if reviews else None
