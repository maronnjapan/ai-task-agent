"""AI Orchestrator (SPEC 8, 20): event-driven loop that runs Manager -> Worker -> Review -> replan."""

from __future__ import annotations

import asyncio
import logging
import traceback
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from app.agents.manager import ManagerAgent, ManagerResult, summarize_result
from app.agents.reviewer import ReviewAgent, ReviewResult
from app.agents.worker import WorkerAgent, WorkerResult
from app.context import AppContext
from app.infrastructure.artifact_store import ArtifactStore
from app.llm.configuration import LLMConfig
from app.llm.providers import LLMNotConfiguredError
from app.models.enums import PlanStatus, TaskStatus, WorkItemStatus
from app.orchestrator.event_queue import EventQueue, Trigger
from app.orchestrator.recovery import recover
from app.orchestrator.scheduler import SchedulerService
from app.services.artifact_service import ArtifactService
from app.services.audit_service import AuditService
from app.services.execution_service import ExecutionService
from app.services.notification_service import NotificationService
from app.services.settings_service import SettingsService
from app.services.task_service import TaskService
from app.utils import iso_in, now_iso, parse_iso, to_iso, utcnow

log = logging.getLogger(__name__)

MANAGER_TRIGGERS = {
    "app_started",
    "task_created",
    "task_updated",
    "schedule_due",
    "user_approved",
    "manual_run",
    "reevaluate",
    "approval_resolved",
    "work_item_completed",
    "review_completed",
}
EXTERNAL_TRIGGERS = {
    "task_created",
    "task_updated",
    "user_approved",
    "manual_run",
    "approval_resolved",
    "user_instruction",
    "app_started",
}

AGENT_TIMEOUT_SECONDS = {"manager": 900, "worker": 1800, "review": 900}


@dataclass
class OrchestratorStatus:
    state: str = "idle"
    activity: str | None = None
    current_run_id: str | None = None
    last_run_at: str | None = None
    last_result: str | None = None
    consecutive_no_progress: int = 0
    llm_issue: str | None = None
    cycles: int = 0
    details: dict[str, Any] = field(default_factory=dict)


class Orchestrator:
    def __init__(self, app: AppContext):
        self.app = app
        self.queue = EventQueue(app.db)
        self.manager = ManagerAgent(app)
        self.worker = WorkerAgent(app)
        self.reviewer = ReviewAgent(app)
        self.status = OrchestratorStatus()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._cycle_lock = asyncio.Lock()
        self._instruction_lock = asyncio.Lock()  # one-shot instructions never wait for a running cycle
        self._backup_due = False
        self._paused = False
        self.enabled = True
        self.store = ArtifactStore(app.paths.artifacts)
        app.extras.setdefault("artifact_store", self.store)

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self.queue.bind(loop)
        self._stop = asyncio.Event()
        with self.app.db.session() as session:
            self._paused = SettingsService(session, self.app.settings).get_flag("manager_paused", False)
        summary = recover(self.app)
        self.status.details["recovery"] = summary
        with self.app.db.session() as session:
            persisted = SettingsService(session, self.app.settings).get_raw("orchestrator.no_progress") or {}
            self.status.consecutive_no_progress = int(persisted.get("count", 0))
        self._ensure_reevaluation_scheduled()
        if self.enabled:
            self.queue.push("app_started", {"recovery": summary})
        self._task = asyncio.create_task(self._loop(), name="aiwm-orchestrator")
        self._publish_status()

    async def stop(self) -> None:
        self._stop.set()
        self.queue.wake()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        self.status.state = "stopped"

    # ------------------------------------------------------------------ public controls
    def trigger(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.queue.push(event_type, payload)

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        self._paused = True
        with self.app.db.session() as session:
            SettingsService(session, self.app.settings).set_flag("manager_paused", True)
            AuditService(session).record("manager.paused", "system", None, "user")
        self.status.state = "paused"
        self._publish_status()

    def resume(self) -> None:
        self._paused = False
        with self.app.db.session() as session:
            SettingsService(session, self.app.settings).set_flag("manager_paused", False)
            AuditService(session).record("manager.resumed", "system", None, "user")
        self.status.consecutive_no_progress = 0
        self.status.state = "idle"
        self.queue.push("manual_run", {"reason": "resume"})
        self._publish_status()

    async def wait_idle(self, timeout: float = 600.0) -> None:
        """Wait until no cycle is executing (used before restoring a backup)."""
        try:
            await asyncio.wait_for(self._cycle_lock.acquire(), timeout=timeout)
        except TimeoutError as exc:
            raise RuntimeError("the orchestrator is still busy") from exc
        self._cycle_lock.release()

    def status_dict(self) -> dict[str, Any]:
        with self.app.db.session() as session:
            exec_service = ExecutionService(session)
            from sqlalchemy import func, select

            from app.models import Task

            pending_reviews = int(
                session.execute(
                    select(func.count(Task.id)).where(
                        Task.status == "review_pending", Task.is_deleted.is_(False)
                    )
                ).scalar_one()
            )
            active_plans = len(exec_service.active_plans())
            next_due = SchedulerService(session).next_due_at()
            llm = SettingsService(session, self.app.settings).get_llm()
        llm_ready = True
        llm_issue = self.status.llm_issue
        if self.app.llm_factory is not None:
            provider = self.app.llm_factory.provider_override or llm.manager.provider
            llm_ready = self.app.llm_factory.is_configured(provider)
            if not llm_ready:
                llm_issue = f"{provider} の API キーが設定されていません"
        state = "paused" if self._paused else ("disabled" if not self.enabled else self.status.state)
        return {
            "state": state,
            "activity": self.status.activity,
            "current_run_id": self.status.current_run_id,
            "last_run_at": self.status.last_run_at,
            "last_result": self.status.last_result,
            "next_scheduled_at": to_iso(next_due) if next_due else None,
            "pending_review_count": pending_reviews,
            "active_plan_count": active_plans,
            "queued_events": self.queue.pending_count(),
            "llm_ready": llm_ready,
            "llm_issue": llm_issue,
            "consecutive_no_progress": self.status.consecutive_no_progress,
        }

    async def run_instruction(self, instruction: str, task_ids: list[str] | None = None) -> ManagerResult:
        """One-shot instruction from the task list (SPEC 13.3). Runs immediately."""
        async with self._instruction_lock:
            self._set_state("running", "指示を処理中")
            with self.app.db.session() as session:
                exec_service = ExecutionService(session)
                run = exec_service.start_run(
                    "manager",
                    model=self._model_name("manager"),
                    trigger="user_instruction",
                    input_summary=instruction[:500],
                )
                run_id = run.id
            self.status.current_run_id = run_id
            try:
                text = (
                    instruction if not task_ids else instruction + "\n\n対象タスクID: " + ", ".join(task_ids)
                )
                result = await asyncio.wait_for(
                    self.manager.run(
                        mode="instruction", trigger="user_instruction", instruction=text, run_id=run_id
                    ),
                    timeout=AGENT_TIMEOUT_SECONDS["manager"],
                )
                with self.app.db.session() as session:
                    ExecutionService(session, self.app.broker).finish_run(
                        run_id, "succeeded", result_summary=summarize_result(result)
                    )
                    AuditService(session).record(
                        "manager.instruction",
                        "agent_run",
                        run_id,
                        "user",
                        {"instruction": instruction[:2000], "response": result.text[:4000]},
                    )
                if result.text:
                    self._manager_message(
                        "Manager AI からの返答", result.text, task_id=(task_ids or [None])[0]
                    )
                if result.plan_ids:
                    self.queue.push("reevaluate", {"reason": "instruction_created_plans"})
                self._set_no_progress(0)
                return result
            except Exception as exc:  # noqa: BLE001
                with self.app.db.session() as session:
                    ExecutionService(session, self.app.broker).finish_run(
                        run_id, "failed", error_message=str(exc)[:2000]
                    )
                raise
            finally:
                self.status.current_run_id = None
                self._set_state("idle", None)

    # ------------------------------------------------------------------ main loop
    async def _loop(self) -> None:
        log.info("orchestrator loop started")
        while not self._stop.is_set():
            try:
                timeout = self._next_wait_seconds()
                await self.queue.wait(timeout)
                if self._stop.is_set():
                    break
                if self._paused or not self.enabled:
                    continue
                self._process_due_actions()
                triggers = self.queue.drain()
                if triggers:
                    await self.run_cycle(triggers)
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                log.exception("orchestrator loop error")
                self._set_state("idle", None)
                await asyncio.sleep(5)
        log.info("orchestrator loop stopped")

    def _next_wait_seconds(self) -> float | None:
        if self._paused or not self.enabled:
            return 3600.0
        with self.app.db.session() as session:
            next_due = SchedulerService(session).next_due_at()
        if next_due is None:
            return 300.0
        delta = (next_due - utcnow()).total_seconds()
        return max(0.5, min(delta, 300.0))

    def _process_due_actions(self) -> None:
        with self.app.db.session() as session:
            scheduler = SchedulerService(session)
            for action in scheduler.due():
                scheduler.mark(action, "running")
                payload = scheduler.payload_of(action)
                self.queue.push(
                    "schedule_due",
                    {
                        "action_type": action.action_type,
                        "action_id": action.id,
                        "task_id": action.task_id,
                        "payload": payload,
                    },
                    session=session,
                )
                scheduler.mark(action, "done")
                AuditService(session).record(
                    "schedule.fired",
                    "scheduled_action",
                    action.id,
                    "system",
                    {"action_type": action.action_type},
                )

    async def run_cycle(self, triggers: list[Trigger]) -> None:
        async with self._cycle_lock:
            self.status.cycles += 1
            trigger_types = {t.type for t in triggers}
            external = bool(trigger_types & EXTERNAL_TRIGGERS)
            if external:
                self.status.consecutive_no_progress = 0
            log.info("orchestrator cycle %s triggers=%s", self.status.cycles, sorted(trigger_types))
            self._set_state("running", "状況を確認中")
            try:
                self._run_builtin_checks(triggers)
                if self._backup_due:
                    self._backup_due = False
                    await asyncio.to_thread(self._auto_backup)
                if not self._llm_ready():
                    return
                resumed = self._resume_after_approvals(triggers)
                progress = await self._execute_active_plans() or resumed
                if trigger_types & MANAGER_TRIGGERS:
                    limit = self._limits()["max_consecutive_no_progress"]
                    if not external and self.status.consecutive_no_progress >= limit:
                        log.info(
                            "skipping reevaluation: no progress for %s cycles",
                            self.status.consecutive_no_progress,
                        )
                        self._note_no_progress_limit(limit)
                    else:
                        result = await self._run_manager(trigger=",".join(sorted(trigger_types)))
                        if result is not None:
                            progress = progress or result.made_progress
                            if result.plan_ids:
                                self._manager_message("Manager AI が作業を開始しました", result.text)
                                progress = await self._execute_active_plans() or progress
                if progress:
                    self._set_no_progress(0)
                    self.queue.push("reevaluate", {"reason": "progress"})
                else:
                    self._set_no_progress(self.status.consecutive_no_progress + 1)
            except Exception as exc:  # noqa: BLE001
                log.exception("cycle failed")
                self.status.last_result = f"error: {exc}"
                with self.app.db.session() as session:
                    AuditService(session).record(
                        "orchestrator.error",
                        "system",
                        None,
                        "system",
                        {"error": str(exc)[:2000], "trace": traceback.format_exc()[-4000:]},
                    )
                    SchedulerService(session).schedule(
                        "retry_after_error",
                        iso_in(minutes=5),
                        payload={"error": str(exc)[:500]},
                        replace=True,
                    )
            finally:
                self._ensure_reevaluation_scheduled()
                self.status.last_run_at = now_iso()
                self._set_state("idle", None)

    # ------------------------------------------------------------------ helpers
    def _limits(self) -> dict[str, int]:
        with self.app.db.session() as session:
            manager = SettingsService(session, self.app.settings).get_manager()
        return {
            "max_replanning_attempts": manager.max_replanning_attempts,
            "max_worker_retries": manager.max_worker_retries,
            "max_consecutive_no_progress": manager.max_consecutive_no_progress,
            "reevaluation_interval_minutes": manager.reevaluation_interval_minutes,
        }

    def _set_no_progress(self, count: int) -> None:
        self.status.consecutive_no_progress = count
        with self.app.db.session() as session:
            SettingsService(session, self.app.settings).set_raw(
                "orchestrator.no_progress", {"count": count, "updated_at": now_iso()}
            )

    def _note_no_progress_limit(self, limit: int) -> None:
        """SPEC 7.5: when a limit is reached, persist the situation and tell the user once."""
        with self.app.db.session() as session:
            AuditService(session).record(
                "orchestrator.no_progress_limit",
                "system",
                None,
                "system",
                {"limit": limit, "count": self.status.consecutive_no_progress},
            )
        self._notify(
            "AI の自動再評価を一時停止しました",
            f"{limit} 回連続で進捗がなかったため、次の予定時刻またはタスクの変更まで再評価を待機します。",
            level="low",
            dedupe_key="orchestrator:no_progress",
            source="orchestrator",
            dedupe_minutes=24 * 60,
        )

    def _manager_message(self, title: str, text: str, task_id: str | None = None) -> None:
        """Store the Manager's own words as an in-app message (SPEC 18.3 'AI Managerメッセージ')."""
        text = (text or "").strip()
        if not text:
            return
        with self.app.db.session() as session:
            settings = SettingsService(session, self.app.settings).get_notifications()
            NotificationService(session, settings, self.app.platform, self.app.broker).create(
                title,
                text[:4000],
                level="low",
                task_id=task_id,
                source="manager",
                channel="manager_message",
                force=True,
            )

    def _resume_after_approvals(self, triggers: list[Trigger]) -> bool:
        """An approved external_write call re-queues the work item that was blocked waiting for it."""
        resumed = False
        with self.app.db.session() as session:
            from app.services.approval_service import ApprovalService

            exec_service = ExecutionService(session, self.app.broker)
            task_service = TaskService(session, self.app.broker)
            for trigger in triggers:
                if trigger.type != "approval_resolved" or trigger.payload.get("status") != "approved":
                    continue
                approval_id = trigger.payload.get("approval_id")
                if not approval_id:
                    continue
                try:
                    approval = ApprovalService(session).get(approval_id)
                except Exception:  # noqa: BLE001
                    continue
                if not approval.work_item_id or approval.executed_at:
                    continue
                try:
                    item = exec_service.get_work_item(approval.work_item_id)
                except Exception:  # noqa: BLE001
                    continue
                if item.status not in (WorkItemStatus.BLOCKED, WorkItemStatus.FAILED):
                    continue
                exec_service.set_work_item_status(item.id, WorkItemStatus.PENDING)
                plan = exec_service.get_plan(item.execution_plan_id)
                if plan.status in (PlanStatus.BLOCKED, PlanStatus.FAILED, PlanStatus.REVIEWING):
                    exec_service.set_plan_status(plan.id, PlanStatus.RUNNING)
                for task_id in exec_service.plan_task_ids(plan.id):
                    task = task_service.get(task_id)
                    if task.status == TaskStatus.BLOCKED:
                        task_service.set_status(
                            task_id, TaskStatus.IN_PROGRESS, actor="system", summary="承認により再開"
                        )
                AuditService(session).record(
                    "work_item.resumed_after_approval",
                    "work_item",
                    item.id,
                    "system",
                    {"approval_id": approval_id},
                )
                resumed = True
        return resumed

    def _model_name(self, agent: str) -> str:
        with self.app.db.session() as session:
            llm = SettingsService(session, self.app.settings).get_llm()
        cfg = getattr(llm, agent)
        provider = (
            self.app.llm_factory.provider_override
            if self.app.llm_factory and self.app.llm_factory.provider_override
            else cfg.provider
        )
        return f"{provider}:{cfg.model}"

    def _llm_ready(self) -> bool:
        if self.app.llm_factory is None:
            self.status.llm_issue = "LLM factory not initialised"
            return False
        with self.app.db.session() as session:
            llm = SettingsService(session, self.app.settings).get_llm()
        for agent in ("manager", "worker", "review"):
            config = LLMConfig.from_settings(agent, getattr(llm, agent))
            provider = self.app.llm_factory.provider_override or config.provider
            if not self.app.llm_factory.is_configured(provider):
                issue = f"{provider} の API キーが設定されていないため AI 実行を見送りました"
                if self.status.llm_issue != issue:
                    self.status.llm_issue = issue
                    self._notify(
                        "API キーが未設定です",
                        issue + "。設定画面から登録してください。",
                        level="high",
                        dedupe_key="system:llm_missing",
                    )
                return False
        self.status.llm_issue = None
        return True

    def _notify(
        self,
        title: str,
        body: str = "",
        level: str = "normal",
        task_id: str | None = None,
        dedupe_key: str | None = None,
        source: str = "orchestrator",
        dedupe_minutes: int | None = None,
    ) -> None:
        with self.app.db.session() as session:
            settings = SettingsService(session, self.app.settings).get_notifications()
            NotificationService(session, settings, self.app.platform, self.app.broker).create(
                title,
                body,
                level=level,
                task_id=task_id,
                dedupe_key=dedupe_key,
                source=source,
                dedupe_minutes=dedupe_minutes,
            )

    def _set_state(self, state: str, activity: str | None) -> None:
        self.status.state = state
        self.status.activity = activity
        self._publish_status()

    def _publish_status(self) -> None:
        try:
            self.app.broker.publish(
                "manager.status",
                {
                    "state": "paused" if self._paused else self.status.state,
                    "activity": self.status.activity,
                    "run_id": self.status.current_run_id,
                },
            )
        except Exception:  # noqa: BLE001
            pass

    def _ensure_reevaluation_scheduled(self) -> None:
        limits = self._limits()
        with self.app.db.session() as session:
            scheduler = SchedulerService(session)
            if not scheduler.pending(action_type="manager_reevaluate"):
                scheduler.schedule(
                    "manager_reevaluate",
                    iso_in(minutes=limits["reevaluation_interval_minutes"]),
                    payload={"by": "orchestrator"},
                )

    # ------------------------------------------------------------------ built-in (non-LLM) proactive checks
    def _run_builtin_checks(self, triggers: list[Trigger]) -> None:
        """Deterministic reminders: approaching deadlines and stale user reviews (SPEC 18.1, 20.1)."""
        with self.app.db.session() as session:
            settings_service = SettingsService(session, self.app.settings)
            notif_settings = settings_service.get_notifications()
            manager = settings_service.get_manager()
            notifier = NotificationService(session, notif_settings, self.app.platform, self.app.broker)
            tasks, _ = TaskService(session).list(include_completed=False, limit=1000)
            now = utcnow()
            horizon_hours = {"low": 12, "normal": 24, "high": 72}.get(manager.reminder_aggressiveness, 24)
            today = now.strftime("%Y-%m-%d")
            for task in tasks:
                due = parse_iso(task.due_at) if task.due_at else None
                if due is None:
                    continue
                remaining = due - now
                if remaining <= timedelta(hours=horizon_hours):
                    if remaining.total_seconds() < 0:
                        title, body, level = "期限超過", f"「{task.title}」の期限を過ぎています。", "high"
                    else:
                        hours = int(remaining.total_seconds() // 3600)
                        title, body, level = (
                            "期限が近づいています",
                            f"「{task.title}」の期限まであと約{hours}時間です。",
                            "normal",
                        )
                    notifier.create(
                        title,
                        body,
                        level=level,
                        task_id=task.id,
                        dedupe_key=f"due:{task.id}:{today}",
                        source="scheduler",
                        dedupe_minutes=24 * 60,
                    )
            if notif_settings.pending_review_reminder_hours > 0:
                for task in tasks:
                    if task.status != TaskStatus.REVIEW_PENDING:
                        continue
                    updated = parse_iso(task.updated_at)
                    if updated and now - updated >= timedelta(
                        hours=notif_settings.pending_review_reminder_hours
                    ):
                        notifier.create(
                            "確認待ちの成果物があります",
                            f"「{task.title}」の成果物が確認待ちです。",
                            level="low",
                            task_id=task.id,
                            dedupe_key=f"review_reminder:{task.id}:{today}",
                            source="scheduler",
                            dedupe_minutes=24 * 60,
                        )
            for trigger in triggers:
                if trigger.type == "schedule_due" and trigger.payload.get("action_type") == "notify":
                    payload = trigger.payload.get("payload") or {}
                    notifier.create(
                        payload.get("title") or "リマインダー",
                        payload.get("note") or payload.get("body") or "",
                        level=payload.get("level", "normal"),
                        task_id=trigger.payload.get("task_id"),
                        source="scheduler",
                    )
                if trigger.type == "schedule_due" and trigger.payload.get("action_type") == "auto_backup":
                    self._backup_due = True  # performed off the event loop after the checks
            backup = settings_service.get_backup()
            if backup.auto_backup_interval_hours > 0:
                scheduler = SchedulerService(session)
                if not scheduler.pending(action_type="auto_backup"):
                    scheduler.schedule("auto_backup", iso_in(hours=backup.auto_backup_interval_hours))

    def _auto_backup(self) -> None:
        """Blocking backup; run via ``asyncio.to_thread`` so the event loop stays responsive."""
        from pathlib import Path

        from app import __version__
        from app.infrastructure.backup import BackupService

        with self.app.db.session() as session:
            settings = SettingsService(session, self.app.settings).get_backup()
        directory = Path(settings.directory) if settings.directory else None
        try:
            service = BackupService(self.app.paths, __version__)
            info = service.create(directory)
            service.prune(settings.keep_last, directory)
            with self.app.db.session() as session:
                AuditService(session).record(
                    "backup.auto", "system", None, "system", {"path": str(info.path)}
                )
        except Exception as exc:  # noqa: BLE001
            log.exception("auto backup failed")
            with self.app.db.session() as session:
                AuditService(session).record("backup.failed", "system", None, "system", {"error": str(exc)})

    # ------------------------------------------------------------------ manager
    async def _run_manager(
        self, trigger: str, mode: str = "evaluate", replan_plan_id: str | None = None
    ) -> ManagerResult | None:
        self._set_state("running", "計画を検討中" if mode == "evaluate" else "再計画中")
        with self.app.db.session() as session:
            run = ExecutionService(session, self.app.broker).start_run(
                "manager",
                execution_plan_id=replan_plan_id,
                model=self._model_name("manager"),
                trigger=trigger,
                input_summary=f"mode={mode}",
            )
            run_id = run.id
        self.status.current_run_id = run_id
        try:
            result = await asyncio.wait_for(
                self.manager.run(mode=mode, trigger=trigger, replan_plan_id=replan_plan_id, run_id=run_id),
                timeout=AGENT_TIMEOUT_SECONDS["manager"],
            )
            with self.app.db.session() as session:
                ExecutionService(session, self.app.broker).finish_run(
                    run_id, "succeeded", result_summary=summarize_result(result)
                )
            self.status.last_result = summarize_result(result)
            return result
        except LLMNotConfiguredError as exc:
            self.status.llm_issue = str(exc)
            with self.app.db.session() as session:
                ExecutionService(session, self.app.broker).finish_run(
                    run_id, "failed", error_message=str(exc)
                )
            return None
        except Exception as exc:  # noqa: BLE001
            log.exception("manager run failed")
            with self.app.db.session() as session:
                ExecutionService(session, self.app.broker).finish_run(
                    run_id, "failed", error_message=str(exc)[:2000]
                )
            self.status.last_result = f"manager error: {exc}"
            self._notify(
                "Manager AI の実行に失敗しました", str(exc)[:300], level="normal", dedupe_key="manager:error"
            )
            return None
        finally:
            self.status.current_run_id = None

    # ------------------------------------------------------------------ plan execution
    async def _execute_active_plans(self) -> bool:
        progress = False
        guard = 0
        while guard < 20:
            guard += 1
            with self.app.db.session() as session:
                plans = [
                    p.id
                    for p in ExecutionService(session).active_plans()
                    if p.status in (PlanStatus.PLANNED, PlanStatus.RUNNING)
                ]
            if not plans:
                break
            for plan_id in plans:
                if self._stop.is_set() or self._paused:
                    return progress
                changed = await self.execute_plan(plan_id)
                progress = progress or changed
        return progress

    async def execute_plan(self, plan_id: str) -> bool:
        """Run all work items of a plan in dependency order, then review (SPEC 8.2)."""
        limits = self._limits()
        with self.app.db.session() as session:
            exec_service = ExecutionService(session, self.app.broker)
            plan = exec_service.get_plan(plan_id)
            if plan.status not in (PlanStatus.PLANNED, PlanStatus.RUNNING):
                return False
            if plan.status == PlanStatus.PLANNED:
                exec_service.set_plan_status(plan.id, PlanStatus.RUNNING)
            task_service = TaskService(session, self.app.broker)
            for task_id in exec_service.plan_task_ids(plan.id):
                task = task_service.get(task_id)
                if task.status in (TaskStatus.TODO, TaskStatus.BLOCKED):
                    task_service.set_status(
                        task_id, TaskStatus.IN_PROGRESS, actor="ai", summary="AI が作業を開始"
                    )
            items = exec_service.list_work_items(plan.id)
        if not items:
            self._finish_plan_without_items(plan_id)
            return True
        progress = False
        while True:
            if self._stop.is_set() or self._paused:
                return progress
            with self.app.db.session() as session:
                exec_service = ExecutionService(session)
                next_item = exec_service.next_runnable(plan_id)
                next_id = next_item.id if next_item else None
            if next_id is None:
                break
            await self._run_work_item(plan_id, next_id, limits["max_worker_retries"])
            progress = True
            with self.app.db.session() as session:
                ExecutionService(session, self.app.broker).block_unrunnable(plan_id)
        await self._review_plan(plan_id, limits)
        return True

    async def _run_work_item(self, plan_id: str, work_item_id: str, max_retries: int) -> None:
        with self.app.db.session() as session:
            exec_service = ExecutionService(session, self.app.broker)
            item = exec_service.set_work_item_status(work_item_id, WorkItemStatus.RUNNING)
            title = item.title
            run = exec_service.start_run(
                "worker",
                execution_plan_id=plan_id,
                work_item_id=work_item_id,
                model=self._model_name("worker"),
                trigger="plan_execution",
                input_summary=item.description[:500],
            )
            run_id = run.id
        self.status.current_run_id = run_id
        self._set_state("running", f"作業中: {title}")
        try:
            result: WorkerResult = await asyncio.wait_for(
                self.worker.run(plan_id, work_item_id, run_id=run_id), timeout=AGENT_TIMEOUT_SECONDS["worker"]
            )
            with self.app.db.session() as session:
                exec_service = ExecutionService(session, self.app.broker)
                exec_service.set_work_item_status(work_item_id, result.status, result.to_dict(work_item_id))
                exec_service.finish_run(
                    run_id,
                    "succeeded" if result.status != "failed" else "failed",
                    result_summary=result.summary[:2000],
                    error_message=None if result.status != "failed" else result.summary[:2000],
                )
                if result.status == "failed":
                    self._maybe_retry(session, work_item_id, max_retries, result.summary)
                AuditService(session).record(
                    "work_item.completed",
                    "work_item",
                    work_item_id,
                    "ai",
                    {"status": result.status, "artifacts": result.artifact_ids},
                )
            self.queue.push("work_item_completed", {"work_item_id": work_item_id, "status": result.status})
        except Exception as exc:  # noqa: BLE001
            log.exception("worker run failed")
            with self.app.db.session() as session:
                exec_service = ExecutionService(session, self.app.broker)
                exec_service.finish_run(run_id, "failed", error_message=str(exc)[:2000])
                exec_service.set_work_item_status(
                    work_item_id,
                    WorkItemStatus.FAILED,
                    {
                        "work_item_id": work_item_id,
                        "status": "failed",
                        "summary": f"error: {exc}"[:1000],
                        "artifact_ids": [],
                        "sources": [],
                        "blockers": ["exception"],
                    },
                )
                self._maybe_retry(session, work_item_id, max_retries, str(exc))
        finally:
            self.status.current_run_id = None

    def _maybe_retry(self, session, work_item_id: str, max_retries: int, reason: str) -> None:
        exec_service = ExecutionService(session, self.app.broker)
        item = exec_service.get_work_item(work_item_id)
        if item.retry_count < max_retries:
            item.retry_count += 1
            item.status = WorkItemStatus.PENDING
            item.updated_at = now_iso()
            session.flush()
            AuditService(session).record(
                "work_item.retry",
                "work_item",
                work_item_id,
                "system",
                {"attempt": item.retry_count, "reason": reason[:500]},
            )
        else:
            AuditService(session).record(
                "work_item.retry_exhausted",
                "work_item",
                work_item_id,
                "system",
                {"attempts": item.retry_count},
            )

    def _finish_plan_without_items(self, plan_id: str) -> None:
        with self.app.db.session() as session:
            exec_service = ExecutionService(session, self.app.broker)
            exec_service.set_plan_status(plan_id, PlanStatus.FAILED)
            for task_id in exec_service.plan_task_ids(plan_id):
                TaskService(session, self.app.broker).set_status(
                    task_id, TaskStatus.TODO, actor="system", summary="計画に作業がなかったため差し戻し"
                )
            AuditService(session).record("plan.empty", "execution_plan", plan_id, "system")

    async def _review_plan(self, plan_id: str, limits: dict[str, int]) -> None:
        with self.app.db.session() as session:
            exec_service = ExecutionService(session, self.app.broker)
            exec_service.set_plan_status(plan_id, PlanStatus.REVIEWING)
            items = exec_service.list_work_items(plan_id)
            task_ids = exec_service.plan_task_ids(plan_id)
            succeeded = [i for i in items if i.status == WorkItemStatus.SUCCEEDED]
            blocked = [i for i in items if i.status == WorkItemStatus.BLOCKED]
            run = exec_service.start_run(
                "review",
                execution_plan_id=plan_id,
                model=self._model_name("review"),
                trigger="plan_execution",
            )
            run_id = run.id
        self.status.current_run_id = run_id
        self._set_state("running", "レビュー中")
        error: str | None = None
        try:
            if succeeded:
                result: ReviewResult = await asyncio.wait_for(
                    self.reviewer.run(plan_id, run_id=run_id), timeout=AGENT_TIMEOUT_SECONDS["review"]
                )
            else:
                status = (
                    "blocked"
                    if blocked and not any(i.status == WorkItemStatus.FAILED for i in items)
                    else "failed"
                )
                from app.utils import loads

                summaries = [
                    f"- {i.title}: {(loads(i.result, {}) or {}).get('summary', i.status)}" for i in items
                ]
                result = ReviewResult(
                    status=status,
                    feedback="作業が完了しなかったため不合格です。\n" + "\n".join(summaries),
                    task_results=[{"task_id": t, "status": status, "feedback": None} for t in task_ids],
                )
        except Exception as exc:  # noqa: BLE001
            log.exception("review failed")
            error = str(exc)[:2000]
            result = ReviewResult(
                status="failed", feedback=f"Review AI の実行に失敗しました: {exc}"[:1000], task_results=[]
            )
        with self.app.db.session() as session:
            exec_service = ExecutionService(session, self.app.broker)
            # Results are sanitised (unknown task ids dropped, invalid statuses mapped) so that a
            # malformed verdict can never leave the plan stuck in "reviewing".
            review = exec_service.record_review(
                plan_id, run_id, result.status, result.feedback, result.task_results, strict=False
            )
            if error:
                exec_service.finish_run(run_id, "failed", result_summary=None, error_message=error)
            else:
                exec_service.finish_run(
                    run_id, "succeeded", result_summary=f"{result.status}: {result.feedback[:500]}"
                )
            review_id = review.id
        self.status.current_run_id = None
        self.queue.push("review_completed", {"plan_id": plan_id, "status": result.status})
        await self._apply_review(plan_id, review_id, limits)

    async def _apply_review(self, plan_id: str, review_id: str, limits: dict[str, int]) -> None:
        with self.app.db.session() as session:
            exec_service = ExecutionService(session, self.app.broker)
            task_service = TaskService(session, self.app.broker)
            artifact_service = ArtifactService(session, self.store, self.app.broker)
            plan = exec_service.get_plan(plan_id)
            review = next(r for r in exec_service.list_reviews(plan_id) if r.id == review_id)
            results = {r.task_id: r for r in review.task_results}
            passed = [t for t, r in results.items() if r.status == "passed"]
            failed = [t for t, r in results.items() if r.status == "failed"]
            blocked = [t for t, r in results.items() if r.status == "blocked"]
            titles = {t: task_service.get(t).title for t in results}
            for task_id in passed:
                task_service.set_status(
                    task_id, TaskStatus.REVIEW_PENDING, actor="ai", summary="Review AI 合格: ユーザー確認待ち"
                )
                for artifact in artifact_service.list_for_task(task_id):
                    if (
                        artifact.execution_plan_id in {p.id for p in exec_service.plan_chain(plan_id)}
                        and artifact.status == "draft"
                    ):
                        artifact_service.set_status(artifact.id, "review_pending", actor="ai")
            for task_id in blocked:
                task_service.set_status(
                    task_id, TaskStatus.BLOCKED, actor="ai", summary="Review AI: 追加情報が必要"
                )
                task_service.add_context(
                    task_id,
                    f"Review AI からの確認事項: {results[task_id].feedback or review.feedback}",
                    source="review_blocked",
                    actor="ai",
                )
            # Per-task verdicts decide the plan outcome (SPEC 12): any failed task means replanning.
            if failed:
                exec_service.set_plan_status(plan_id, PlanStatus.FAILED)
            elif blocked:
                exec_service.set_plan_status(plan_id, PlanStatus.BLOCKED)
            else:
                exec_service.set_plan_status(plan_id, PlanStatus.PASSED)
            attempt = plan.replanning_attempt
            feedback = review.feedback
        if passed:
            names = "、".join(titles[t] for t in passed)
            self._notify(
                "成果物の確認をお願いします",
                f"「{names}」の作業が完了し、確認待ちになりました。",
                level="normal",
                task_id=passed[0],
                dedupe_key=f"review_pending:{plan_id}",
                source="manager",
            )
        if blocked:
            names = "、".join(titles[t] for t in blocked)
            self._notify(
                "追加情報が必要です",
                f"「{names}」を進めるには追加の情報が必要です。タスク詳細を確認してください。",
                level="normal",
                task_id=blocked[0],
                dedupe_key=f"blocked:{plan_id}",
                source="manager",
            )
        if failed:
            if attempt < limits["max_replanning_attempts"]:
                result = await self._run_manager(
                    trigger="review_failed", mode="replan", replan_plan_id=plan_id
                )
                if result is None or not result.plan_ids:
                    self._exhaust(plan_id, failed, titles, "再計画が作成されなかったため作業を停止しました。")
                else:
                    with self.app.db.session() as session:
                        covered: set[str] = set()
                        for new_plan_id in result.plan_ids:
                            covered.update(ExecutionService(session).plan_task_ids(new_plan_id))
                    uncovered = [t for t in failed if t not in covered]
                    if uncovered:
                        self._exhaust(
                            plan_id, uncovered, titles, "再計画の対象に含まれなかったため作業を停止しました。"
                        )
            else:
                self._exhaust(
                    plan_id,
                    failed,
                    titles,
                    f"再計画の上限（{limits['max_replanning_attempts']}回）に達したため作業を停止しました。\n{feedback[:400]}",
                )

    def _exhaust(self, plan_id: str, failed: list[str], titles: dict[str, str], message: str) -> None:
        with self.app.db.session() as session:
            task_service = TaskService(session, self.app.broker)
            for task_id in failed:
                task_service.set_status(
                    task_id, TaskStatus.BLOCKED, actor="system", summary="再試行上限に到達"
                )
                task_service.add_context(task_id, message, source="retry_exhausted", actor="system")
            AuditService(session).record(
                "plan.exhausted", "execution_plan", plan_id, "system", {"tasks": failed, "message": message}
            )
        names = "、".join(titles.get(t, t) for t in failed)
        self._notify(
            "AI の作業を停止しました",
            f"「{names}」: {message}",
            level="high",
            task_id=failed[0] if failed else None,
            dedupe_key=f"exhausted:{plan_id}",
            source="manager",
        )
