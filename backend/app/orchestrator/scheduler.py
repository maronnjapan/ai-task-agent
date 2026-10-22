"""Scheduled actions persisted in SQLite (SPEC 20)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ScheduledAction
from app.services.audit_service import AuditService
from app.utils import dumps, loads, now_iso, parse_iso, utcnow

ACTION_TYPES = {
    "manager_reevaluate",
    "due_check",
    "notify",
    "remind_pending_review",
    "retry_after_error",
    "auto_backup",
}


class SchedulerService:
    def __init__(self, session: Session):
        self.session = session

    def schedule(
        self,
        action_type: str,
        scheduled_at: str,
        task_id: str | None = None,
        execution_plan_id: str | None = None,
        payload: dict | None = None,
        replace: bool = False,
    ) -> ScheduledAction:
        parse_iso(scheduled_at)  # validate
        if replace:
            for row in self.pending(action_type=action_type, task_id=task_id):
                row.status = "cancelled"
        action = ScheduledAction(
            action_type=action_type,
            scheduled_at=scheduled_at,
            task_id=task_id,
            execution_plan_id=execution_plan_id,
            payload=dumps(payload) if payload else None,
        )
        self.session.add(action)
        self.session.flush()
        AuditService(self.session).record("schedule.created", "scheduled_action", action.id, "system", {"action_type": action_type, "scheduled_at": scheduled_at})
        return action

    def pending(self, action_type: str | None = None, task_id: str | None = None) -> list[ScheduledAction]:
        stmt = select(ScheduledAction).where(ScheduledAction.status == "pending")
        if action_type:
            stmt = stmt.where(ScheduledAction.action_type == action_type)
        if task_id:
            stmt = stmt.where(ScheduledAction.task_id == task_id)
        return list(self.session.execute(stmt.order_by(ScheduledAction.scheduled_at)).scalars())

    def due(self, now: datetime | None = None) -> list[ScheduledAction]:
        now_text = (now or utcnow()).isoformat()
        return list(
            self.session.execute(
                select(ScheduledAction)
                .where(ScheduledAction.status == "pending", ScheduledAction.scheduled_at <= now_text)
                .order_by(ScheduledAction.scheduled_at)
            ).scalars()
        )

    def next_due_at(self) -> datetime | None:
        row = self.session.execute(
            select(ScheduledAction.scheduled_at).where(ScheduledAction.status == "pending").order_by(ScheduledAction.scheduled_at).limit(1)
        ).scalar_one_or_none()
        return parse_iso(row) if row else None

    def mark(self, action: ScheduledAction, status: str) -> None:
        action.status = status
        if status == "done":
            action.executed_at = now_iso()
        self.session.flush()

    def reset_running(self) -> int:
        """Recovery: actions left in ``running`` by a crash are retried."""
        count = 0
        for row in self.session.execute(select(ScheduledAction).where(ScheduledAction.status == "running")).scalars():
            row.status = "pending"
            count += 1
        self.session.flush()
        return count

    def cancel(self, action_id: str) -> bool:
        row = self.session.get(ScheduledAction, action_id)
        if row is None or row.status != "pending":
            return False
        row.status = "cancelled"
        self.session.flush()
        return True

    def list(self, limit: int = 100) -> list[ScheduledAction]:
        return list(self.session.execute(select(ScheduledAction).order_by(ScheduledAction.scheduled_at.desc()).limit(limit)).scalars())

    @staticmethod
    def payload_of(action: ScheduledAction) -> dict:
        return loads(action.payload, {}) or {}
