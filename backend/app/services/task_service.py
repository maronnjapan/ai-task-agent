"""Task and category management with version history (SPEC 9)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.events import EventBroker
from app.models import Category, Task, TaskArtifact, TaskContext, TaskVersion
from app.models.enums import Actor, TaskStatus
from app.repositories import CategoryRepository, MemoryRepository, TaskRepository
from app.schemas.tasks import TaskCreate, TaskUpdate
from app.services.audit_service import AuditService
from app.services.errors import NotFoundError, ValidationError
from app.utils import dumps, loads, now_iso, parse_iso

SNAPSHOT_FIELDS = ("title", "description", "due_at", "category_id", "status", "assignee")

ACTIVITY_LABELS = {
    "planned": "計画済み",
    "running": "調査中",
    "reviewing": "レビュー中",
}


def snapshot(task: Task) -> dict[str, Any]:
    return {name: getattr(task, name) for name in SNAPSHOT_FIELDS}


def normalize_datetime(value: str | None) -> str | None:
    """Store date-times as UTC ISO-8601 so that string comparisons are chronological (SPEC 23.5)."""
    if value is None or not str(value).strip():
        return None
    try:
        parsed = parse_iso(str(value))
    except ValueError as exc:
        raise ValidationError(f"Invalid date-time: {value}") from exc
    return parsed.isoformat() if parsed else None


class CategoryService:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[tuple[Category, int]]:
        return CategoryRepository(self.session).with_task_counts()

    def get(self, category_id: str) -> Category:
        category = self.session.get(Category, category_id)
        if category is None:
            raise NotFoundError("Category not found")
        return category

    def create(self, name: str) -> Category:
        name = name.strip()
        if not name:
            raise ValidationError("Category name is required")
        if CategoryRepository(self.session).by_name(name) is not None:
            raise ValidationError("Category already exists")
        category = Category(name=name)
        self.session.add(category)
        self.session.flush()
        return category

    def update(self, category_id: str, name: str) -> Category:
        category = self.get(category_id)
        name = name.strip()
        if not name:
            raise ValidationError("Category name is required")
        category.name = name
        self.session.flush()
        return category

    def delete(self, category_id: str) -> None:
        category = self.get(category_id)
        for task in CategoryRepository(self.session).tasks_in(category_id):
            task.category_id = None
        # Task memories keep their task; category memories lose their container and are deleted.
        for memory in MemoryRepository(self.session).by_category(category_id):
            if memory.scope == "task":
                memory.category_id = None
            else:
                self.session.delete(memory)
        self.session.flush()
        self.session.delete(category)
        self.session.flush()


class TaskService:
    def __init__(self, session: Session, broker: EventBroker | None = None):
        self.session = session
        self.broker = broker
        self.audit = AuditService(session)

    # --- queries ------------------------------------------------------
    def get(self, task_id: str, include_deleted: bool = False) -> Task:
        task = self.session.get(Task, task_id)
        if task is None or (task.is_deleted and not include_deleted):
            raise NotFoundError("Task not found")
        return task

    def list(
        self,
        status: str | None = None,
        category_id: str | None = None,
        assignee: str | None = None,
        search: str | None = None,
        include_deleted: bool = False,
        include_completed: bool = True,
        limit: int = 100,
        offset: int = 0,
        order: str = "due",
    ) -> tuple[list[Task], int]:
        return TaskRepository(self.session).list(
            limit=limit,
            offset=offset,
            status=status,
            category_id=category_id,
            assignee=assignee,
            search=search,
            include_deleted=include_deleted,
            include_completed=include_completed,
            order=order,
        )

    def active_tasks(self) -> list[Task]:
        rows, _ = self.list(include_completed=False, limit=10_000)
        return rows

    def decorate(self, task: Task) -> dict[str, Any]:
        """Extra UI fields: AI activity, pending artifact count, active plan, chat count."""
        repo = TaskRepository(self.session)
        data: dict[str, Any] = {
            "category_name": task.category.name if task.category else None,
            "pending_artifacts": repo.pending_artifact_count(task.id),
            "active_plan_id": None,
            "ai_activity": None,
            "open_chats": repo.chat_count(task.id),
        }
        plan_row = repo.active_plan(task.id)
        if plan_row is not None:
            data["active_plan_id"] = plan_row.id
            if plan_row.status == "running":
                running = repo.running_work_item(plan_row.id)
                data["ai_activity"] = (
                    "資料作成中" if running and "作成" in (running.title or "") else "調査中"
                )
            else:
                data["ai_activity"] = ACTIVITY_LABELS.get(plan_row.status)
        if task.status == TaskStatus.REVIEW_PENDING:
            data["ai_activity"] = "確認待ち"
        elif task.status == TaskStatus.BLOCKED:
            data["ai_activity"] = "追加情報待ち"
        return data

    # --- mutations ----------------------------------------------------
    def create(self, data: TaskCreate, actor: str = Actor.USER, change_summary: str | None = None) -> Task:
        if data.category_id:
            CategoryService(self.session).get(data.category_id)
        task = Task(
            title=data.title.strip(),
            description=data.description,
            due_at=normalize_datetime(data.due_at),
            category_id=data.category_id,
            status=str(data.status),
            assignee=str(data.assignee),
        )
        self.session.add(task)
        self.session.flush()
        self._add_version(task, previous=None, actor=actor, summary=change_summary or "作成")
        self.audit.record("task.created", "task", task.id, actor, {"title": task.title})
        self._publish("task.created", task)
        return task

    def update(self, task_id: str, data: TaskUpdate, actor: str = Actor.USER) -> Task:
        task = self.get(task_id)
        previous = snapshot(task)
        changes = data.model_dump(exclude_unset=True, exclude={"change_summary", "clear"})
        for field in data.clear:
            if field in ("description", "due_at", "category_id"):
                changes[field] = None
        if "category_id" in changes and changes["category_id"]:
            CategoryService(self.session).get(changes["category_id"])
        changed_fields = []
        for field, value in changes.items():
            if field not in SNAPSHOT_FIELDS:
                continue
            if isinstance(value, TaskStatus | str) and field in ("status", "assignee"):
                value = str(value)
            if field == "title" and value is not None:
                value = value.strip()
            if field == "due_at":
                value = normalize_datetime(value)
            if getattr(task, field) != value:
                setattr(task, field, value)
                changed_fields.append(field)
        if not changed_fields:
            return task
        task.updated_at = now_iso()
        self.session.flush()
        summary = data.change_summary or ("変更: " + ", ".join(changed_fields))
        self._add_version(task, previous=previous, actor=actor, summary=summary)
        self.audit.record("task.updated", "task", task.id, actor, {"fields": changed_fields})
        self._publish("task.updated", task)
        return task

    def set_status(
        self, task_id: str, status: str, actor: str = Actor.SYSTEM, summary: str | None = None
    ) -> Task:
        return self.update(
            task_id, TaskUpdate(status=TaskStatus(status), change_summary=summary), actor=actor
        )

    def delete(self, task_id: str, actor: str = Actor.USER) -> Task:
        task = self.get(task_id)
        previous = snapshot(task)
        task.is_deleted = True
        task.updated_at = now_iso()
        self.session.flush()
        self._add_version(task, previous=previous, actor=actor, summary="削除")
        self.audit.record("task.deleted", "task", task.id, actor)
        self._publish("task.deleted", task)
        return task

    def restore(self, task_id: str, actor: str = Actor.USER) -> Task:
        task = self.get(task_id, include_deleted=True)
        task.is_deleted = False
        task.updated_at = now_iso()
        self.session.flush()
        self._add_version(task, previous=snapshot(task), actor=actor, summary="復元")
        self._publish("task.updated", task)
        return task

    def approve(self, task_id: str, actor: str = Actor.USER, comment: str | None = None) -> Task:
        """User approval moves a task to ``completed`` (SPEC 9.2) and approves its pending artifacts."""
        task = self.get(task_id)
        previous = snapshot(task)
        task.status = TaskStatus.COMPLETED
        task.updated_at = now_iso()
        for artifact in self.session.execute(
            select(TaskArtifact).where(
                TaskArtifact.task_id == task.id, TaskArtifact.status == "review_pending"
            )
        ).scalars():
            artifact.status = "approved"
            artifact.updated_at = now_iso()
        for ctx in self.session.execute(
            select(TaskContext).where(TaskContext.task_id == task.id, TaskContext.status == "open")
        ).scalars():
            ctx.status = "resolved"
        self.session.flush()
        self._add_version(
            task, previous=previous, actor=actor, summary="承認して完了" + (f": {comment}" if comment else "")
        )
        self.audit.record("task.approved", "task", task.id, actor, {"comment": comment})
        self._publish("task.updated", task)
        return task

    def reopen(self, task_id: str, actor: str = Actor.USER, reason: str | None = None) -> Task:
        task = self.get(task_id)
        previous = snapshot(task)
        for ctx in self.open_contexts(task.id):
            if ctx.source == "user_hold":
                ctx.status = "resolved"
        task.status = TaskStatus.TODO
        task.updated_at = now_iso()
        self.session.flush()
        self._add_version(
            task, previous=previous, actor=actor, summary="再オープン" + (f": {reason}" if reason else "")
        )
        self.audit.record("task.reopened", "task", task.id, actor, {"reason": reason})
        self._publish("task.updated", task)
        return task

    def request_revision(
        self, task_id: str, instructions: str, kind: str = "revision", actor: str = Actor.USER
    ) -> Task:
        """User asks for changes / more research / hold on a review_pending task (SPEC 12.1)."""
        task = self.get(task_id)
        previous = snapshot(task)
        if kind == "hold":
            new_status = TaskStatus.BLOCKED
        else:
            new_status = TaskStatus.TODO
        if kind != "hold":
            for previous in self.open_contexts(task.id):
                if previous.source == "user_hold":
                    previous.status = "resolved"
        context = TaskContext(
            task_id=task.id,
            context=instructions,
            source=f"user_{kind}",
            status="open",
        )
        self.session.add(context)
        task.status = new_status
        task.updated_at = now_iso()
        for artifact in self.session.execute(
            select(TaskArtifact).where(
                TaskArtifact.task_id == task.id, TaskArtifact.status == "review_pending"
            )
        ).scalars():
            artifact.status = "revision_requested"
            artifact.updated_at = now_iso()
        self.session.flush()
        label = {"revision": "修正依頼", "additional_research": "追加調査依頼", "hold": "保留"}.get(
            kind, kind
        )
        self._add_version(task, previous=previous, actor=actor, summary=f"{label}: {instructions[:80]}")
        self.audit.record(
            "task.revision_requested", "task", task.id, actor, {"kind": kind, "instructions": instructions}
        )
        self._publish("task.updated", task)
        return task

    # --- history ------------------------------------------------------
    def history(self, task_id: str) -> list[TaskVersion]:
        self.get(task_id, include_deleted=True)
        return list(
            self.session.execute(
                select(TaskVersion).where(TaskVersion.task_id == task_id).order_by(TaskVersion.version.desc())
            ).scalars()
        )

    def revert(self, task_id: str, version: int, actor: str = Actor.USER) -> Task:
        task = self.get(task_id, include_deleted=True)
        target = self.session.execute(
            select(TaskVersion).where(TaskVersion.task_id == task_id, TaskVersion.version == version)
        ).scalar_one_or_none()
        if target is None:
            raise NotFoundError("Version not found")
        data = loads(target.revised_content, {})
        previous = snapshot(task)
        for field in SNAPSHOT_FIELDS:
            if field in data:
                setattr(task, field, data[field])
        task.is_deleted = False
        task.updated_at = now_iso()
        self.session.flush()
        self._add_version(task, previous=previous, actor=actor, summary=f"バージョン{version}へ復元")
        self.audit.record("task.reverted", "task", task.id, actor, {"version": version})
        self._publish("task.updated", task)
        return task

    def add_context(
        self, task_id: str, context: str, source: str | None, actor: str = Actor.USER
    ) -> TaskContext:
        self.get(task_id)
        row = TaskContext(task_id=task_id, context=context, source=source)
        self.session.add(row)
        self.session.flush()
        self.audit.record("task.context_added", "task", task_id, actor, {"source": source})
        return row

    def is_on_hold(self, task_id: str) -> bool:
        """A task the user put on hold (SPEC 12.1 保留) must not be resumed by the Manager."""
        return any(c.source == "user_hold" for c in self.open_contexts(task_id))

    def open_contexts(self, task_id: str) -> list[TaskContext]:
        return list(
            self.session.execute(
                select(TaskContext)
                .where(TaskContext.task_id == task_id, TaskContext.status == "open")
                .order_by(TaskContext.created_at)
            ).scalars()
        )

    # --- internals ----------------------------------------------------
    def _add_version(
        self, task: Task, previous: dict[str, Any] | None, actor: str, summary: str
    ) -> TaskVersion:
        current = self.session.execute(
            select(func.max(TaskVersion.version)).where(TaskVersion.task_id == task.id)
        ).scalar_one()
        version = TaskVersion(
            task_id=task.id,
            version=int(current or 0) + 1,
            title=task.title,
            description=task.description,
            revised_content=dumps(snapshot(task)),
            previous_content=dumps(previous) if previous is not None else None,
            changed_by=actor,
            change_summary=summary,
        )
        self.session.add(version)
        self.session.flush()
        return version

    def _publish(self, event_type: str, task: Task) -> None:
        if self.broker is not None:
            self.broker.publish(event_type, {"task_id": task.id, "status": task.status, "title": task.title})
