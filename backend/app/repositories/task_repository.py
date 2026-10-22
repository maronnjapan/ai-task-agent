"""Task and category queries (SPEC 9, 22.2 list view, 29 paging)."""

from __future__ import annotations

from sqlalchemy import Select, func, select

from app.models import Category, ExecutionPlan, RelatedPlanToTask, Task, TaskArtifact, TaskChat, WorkItem
from app.models.enums import TaskStatus
from app.repositories.base import Repository

ACTIVE_PLAN_STATUSES = ("planned", "running", "reviewing")


class TaskRepository(Repository):
    def query(
        self,
        status: str | None = None,
        category_id: str | None = None,
        assignee: str | None = None,
        search: str | None = None,
        include_deleted: bool = False,
        include_completed: bool = True,
        order: str = "due",
    ) -> Select:
        stmt = select(Task)
        if not include_deleted:
            stmt = stmt.where(Task.is_deleted.is_(False))
        if status:
            statuses = [s.strip() for s in status.split(",") if s.strip()]
            stmt = stmt.where(Task.status.in_(statuses))
        elif not include_completed:
            stmt = stmt.where(Task.status != TaskStatus.COMPLETED)
        if category_id:
            stmt = stmt.where(Task.category_id == category_id)
        if assignee:
            stmt = stmt.where(Task.assignee == assignee)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(Task.title.like(like) | Task.description.like(like))
        if order == "created":
            return stmt.order_by(Task.created_at.desc())
        if order == "updated":
            return stmt.order_by(Task.updated_at.desc())
        # due date first (NULLs last), then creation order: the Manager and the UI share this order
        return stmt.order_by(Task.due_at.is_(None), Task.due_at.asc(), Task.created_at.asc())

    def list(self, limit: int = 100, offset: int = 0, **filters) -> tuple[list[Task], int]:
        stmt = self.query(**filters)
        total = self.count(stmt.order_by(None))
        return self.page(stmt, limit, offset), total

    def active_plan(self, task_id: str) -> ExecutionPlan | None:
        return (
            self.session.execute(
                select(ExecutionPlan)
                .join(RelatedPlanToTask, RelatedPlanToTask.execution_plan_id == ExecutionPlan.id)
                .where(RelatedPlanToTask.task_id == task_id)
                .where(ExecutionPlan.status.in_(ACTIVE_PLAN_STATUSES))
                .order_by(ExecutionPlan.created_at.desc())
            )
            .scalars()
            .first()
        )

    def running_work_item(self, plan_id: str) -> WorkItem | None:
        return self.session.execute(
            select(WorkItem)
            .where(WorkItem.execution_plan_id == plan_id, WorkItem.status == "running")
            .limit(1)
        ).scalar_one_or_none()

    def pending_artifact_count(self, task_id: str) -> int:
        return int(
            self.session.execute(
                select(func.count(TaskArtifact.id)).where(
                    TaskArtifact.task_id == task_id, TaskArtifact.status == "review_pending"
                )
            ).scalar_one()
        )

    def chat_count(self, task_id: str) -> int:
        return int(
            self.session.execute(
                select(func.count(TaskChat.id)).where(TaskChat.task_id == task_id)
            ).scalar_one()
        )

    def status_count(self, status: str) -> int:
        return int(
            self.session.execute(
                select(func.count(Task.id)).where(Task.status == status, Task.is_deleted.is_(False))
            ).scalar_one()
        )


class CategoryRepository(Repository):
    def with_task_counts(self) -> list[tuple[Category, int]]:
        rows = self.session.execute(
            select(Category, func.count(Task.id))
            .outerjoin(Task, (Task.category_id == Category.id) & (Task.is_deleted.is_(False)))
            .group_by(Category.id)
            .order_by(Category.name)
        ).all()
        return [(row[0], int(row[1])) for row in rows]

    def by_name(self, name: str) -> Category | None:
        return self.session.execute(select(Category).where(Category.name == name)).scalar_one_or_none()

    def tasks_in(self, category_id: str) -> list[Task]:
        return list(self.session.execute(select(Task).where(Task.category_id == category_id)).scalars())
