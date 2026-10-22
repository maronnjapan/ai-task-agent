"""Restart recovery (SPEC 8.4, 30.5)."""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.context import AppContext
from app.models import AgentRun, ExecutionPlan, WorkItem
from app.orchestrator.scheduler import SchedulerService
from app.services.audit_service import AuditService
from app.utils import dumps, loads, now_iso

log = logging.getLogger(__name__)


def recover(app: AppContext) -> dict[str, int]:
    """Repair state left behind by an abnormal shutdown and report what was found."""
    summary = {"interrupted_runs": 0, "reset_work_items": 0, "resumable_plans": 0, "reset_reviews": 0, "reset_schedules": 0, "pending_user_reviews": 0, "pending_events": 0}
    with app.db.session() as session:
        for run in session.execute(select(AgentRun).where(AgentRun.status == "running")).scalars():
            run.status = "failed"
            run.error_message = "interrupted by restart"
            run.finished_at = now_iso()
            summary["interrupted_runs"] += 1
        for item in session.execute(select(WorkItem).where(WorkItem.status == "running")).scalars():
            item.status = "pending"
            note = loads(item.result, {}) or {}
            note["recovery_note"] = "interrupted by restart; will be re-executed"
            item.result = dumps(note)
            item.updated_at = now_iso()
            summary["reset_work_items"] += 1
        for plan in session.execute(select(ExecutionPlan).where(ExecutionPlan.status.in_(["planned", "running", "reviewing"]))).scalars():
            if plan.status == "reviewing":
                plan.status = "running"
                plan.updated_at = now_iso()
                summary["reset_reviews"] += 1
            summary["resumable_plans"] += 1
        summary["reset_schedules"] = SchedulerService(session).reset_running()
        from sqlalchemy import func

        from app.models import AppEvent, Task

        summary["pending_user_reviews"] = int(session.execute(select(func.count(Task.id)).where(Task.status == "review_pending", Task.is_deleted.is_(False))).scalar_one())
        summary["pending_events"] = int(session.execute(select(func.count(AppEvent.id)).where(AppEvent.status == "pending")).scalar_one())
        AuditService(session).record("system.recovered", "system", None, "system", summary)
    log.info("recovery: %s", summary)
    return summary
