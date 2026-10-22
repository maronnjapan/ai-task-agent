"""Recovery, backup/restore and migration tests (SPEC 30.5)."""

from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app import __version__
from app.context import AppContext
from app.infrastructure.backup import BackupService
from app.infrastructure.database import Database
from app.infrastructure.single_instance import AlreadyRunningError, InstanceLock
from app.models import AgentRun, AppEvent, WorkItem
from app.orchestrator.recovery import recover
from app.orchestrator.runner import Orchestrator
from app.orchestrator.scheduler import SchedulerService
from app.schemas.tasks import TaskCreate
from app.services.artifact_service import ArtifactService
from app.services.execution_service import ExecutionService
from app.services.task_service import TaskService
from app.utils import dumps, iso_in
from tests.test_workflow import review_script, worker_success


def simulate_crash(ctx: AppContext) -> tuple[str, str, str, str]:
    """A plan whose first item succeeded and second item was running when the process died."""
    with ctx.db.session() as s:
        task = TaskService(s).create(TaskCreate(title="復旧対象", assignee="ai"))
        exec_service = ExecutionService(s)
        plan = exec_service.create_plan("復旧テスト", "レポート", [task.id])
        items = exec_service.create_work_items(
            plan.id,
            [
                {"title": "完了済み", "description": "done"},
                {"title": "中断", "description": "interrupted", "depends_on": [0]},
            ],
        )
        exec_service.set_plan_status(plan.id, "running")
        TaskService(s).set_status(task.id, "in_progress")
        exec_service.set_work_item_status(
            items[0].id,
            "succeeded",
            {
                "work_item_id": items[0].id,
                "status": "succeeded",
                "summary": "保存済みの結果",
                "artifact_ids": [],
                "sources": [],
                "blockers": [],
            },
        )
        exec_service.set_work_item_status(items[1].id, "running")
        run = exec_service.start_run("worker", execution_plan_id=plan.id, work_item_id=items[1].id)
        action = SchedulerService(s).schedule("manager_reevaluate", iso_in(minutes=-1))
        SchedulerService(s).mark(action, "running")
        s.add(AppEvent(event_type="task_created", payload=dumps({"task_id": task.id})))
        return task.id, plan.id, items[1].id, run.id


def test_recover_repairs_interrupted_state(ctx: AppContext):
    task_id, plan_id, item_id, run_id = simulate_crash(ctx)
    summary = recover(ctx)
    assert (
        summary["interrupted_runs"] == 1
        and summary["reset_work_items"] == 1
        and summary["resumable_plans"] == 1
    )
    assert summary["reset_schedules"] == 1 and summary["pending_events"] == 1
    with ctx.db.session() as s:
        run = s.get(AgentRun, run_id)
        assert run.status == "failed" and "restart" in run.error_message
        item = s.get(WorkItem, item_id)
        assert item.status == "pending" and "recovery_note" in item.result
        assert ExecutionService(s).get_plan(plan_id).status == "running"
        assert SchedulerService(s).pending(action_type="manager_reevaluate")


@pytest.mark.asyncio
async def test_restart_resumes_plan_and_reuses_saved_results(ctx: AppContext, models):
    task_id, plan_id, item_id, _ = simulate_crash(ctx)
    models["worker"].push(*worker_success("中断分のレポート"))
    models["review"].push(*review_script({task_id: "passed"}))
    models["manager"].push({"content": "確認待ちのため何もしません"})
    orch = Orchestrator(ctx)
    await orch.start()  # runs recovery and queues app_started
    try:
        await orch.run_cycle(orch.queue.drain())
    finally:
        await orch.stop()
    with ctx.db.session() as s:
        items = ExecutionService(s).ordered_work_items(plan_id)
        assert [i.status for i in items] == ["succeeded", "succeeded"]
        assert "保存済みの結果" in items[0].result  # first item's result reused, not re-executed
        worker_runs = [
            r
            for r in s.execute(select(AgentRun)).scalars()
            if r.agent_type == "worker" and r.status == "succeeded"
        ]
        assert len(worker_runs) == 1 and worker_runs[0].work_item_id == item_id
        assert ExecutionService(s).get_plan(plan_id).status == "passed"
        assert TaskService(s).get(task_id).status == "review_pending"
    assert orch.status.details["recovery"]["resumable_plans"] == 1


def test_backup_and_restore_roundtrip(ctx: AppContext):
    with ctx.db.session() as s:
        task = TaskService(s).create(TaskCreate(title="バックアップ対象"))
        artifact = ArtifactService(
            s,
            __import__("app.infrastructure.artifact_store", fromlist=["ArtifactStore"]).ArtifactStore(
                ctx.paths.artifacts
            ),
        ).create("成果物", "# content", task.id)
        artifact_path = artifact.file_path
    ctx.paths.settings_file.write_text('{"theme": "dark"}')
    service = BackupService(ctx.paths, __version__)
    info = service.create(label="test")
    assert info.path.exists() and set(info.includes) == {"database", "artifacts", "config"}
    with zipfile.ZipFile(info.path) as zf:
        names = zf.namelist()
        assert (
            "data/app.db" in names
            and f"artifacts/{artifact_path}" in names
            and "config/settings.json" in names
            and "manifest.json" in names
        )
    # mutate current state, then restore
    with ctx.db.session() as s:
        TaskService(s).create(TaskCreate(title="復元で消えるタスク"))
    (ctx.paths.artifacts / artifact_path).write_text("modified")
    ctx.db.engine.dispose()
    safety = service.restore(info.path)
    assert safety.path.exists() and "pre-restore" in safety.path.name
    ctx.db.reinitialize()
    with ctx.db.session() as s:
        titles = {t.title for t in TaskService(s).list()[0]}
        assert titles == {"バックアップ対象"}
        assert s.execute(text("select count(*) from memories_fts")).scalar_one() == 0
    assert (ctx.paths.artifacts / artifact_path).read_text() == "# content"
    assert service.list()[0].path == safety.path
    assert service.prune(1) == 1 and len(service.list()) == 1
    with pytest.raises(FileNotFoundError):
        service.restore(ctx.paths.backups / "missing.zip")


def test_backup_uses_sqlite_backup_api_while_db_open(ctx: AppContext):
    with ctx.db.session() as s:
        TaskService(s).create(TaskCreate(title="open db"))
    info = BackupService(ctx.paths, __version__).create()
    with zipfile.ZipFile(info.path) as zf:
        data = zf.read("data/app.db")
    copy = ctx.paths.backups / "check.db"
    copy.write_bytes(data)
    conn = sqlite3.connect(copy)
    assert conn.execute("select count(*) from tasks").fetchone()[0] == 1
    conn.close()


def test_alembic_migrations_fresh_database(tmp_path: Path):
    db = Database(tmp_path / "fresh.db", use_migrations=True)
    with db.engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("select name from sqlite_master where type='table'"))}
        assert {
            "tasks",
            "task_versions",
            "execution_plans",
            "work_item_dependencies",
            "memories_fts",
            "alembic_version",
            "mcp_connections",
        } <= tables
        assert conn.execute(text("select version_num from alembic_version")).scalar_one() == "0002"
        assert conn.execute(text("pragma foreign_keys")).scalar_one() == 1
        assert conn.execute(text("pragma journal_mode")).scalar_one() == "wal"
    # idempotent on restart
    Database(tmp_path / "fresh.db", use_migrations=True).dispose()
    db.dispose()


def test_alembic_downgrade_and_upgrade(tmp_path: Path):
    from alembic.config import Config

    from alembic import command
    from app.infrastructure.database import run_migrations

    db = Database(tmp_path / "mig.db", use_migrations=True)
    backend_root = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    with db.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "base")
    with db.engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("select name from sqlite_master where type='table'"))}
        assert "tasks" not in tables and "memories_fts" not in tables
    run_migrations(db.engine)
    with db.engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("select name from sqlite_master where type='table'"))}
        assert "tasks" in tables and "memories_fts" in tables
    db.dispose()


def test_single_instance_lock(tmp_path: Path):
    lock_path = tmp_path / "aiwm.lock"
    first = InstanceLock(lock_path)
    first.acquire()
    assert first.held and lock_path.read_text().strip().isdigit()
    second = InstanceLock(lock_path)
    with pytest.raises(AlreadyRunningError):
        second.acquire()
    first.release()
    assert not first.held
    with InstanceLock(lock_path):
        pass


@pytest.mark.asyncio
async def test_orchestrator_loop_processes_due_actions_and_events(ctx: AppContext, models):
    """End-to-end: the background loop wakes on an event, fires due scheduled actions and runs the manager."""
    models["manager"].push({"content": "nothing to do"}, {"content": "still nothing"})
    with ctx.db.session() as s:
        SchedulerService(s).schedule("manager_reevaluate", iso_in(minutes=-1))
    orch = Orchestrator(ctx)
    await orch.start()
    try:
        import asyncio

        for _ in range(100):
            await asyncio.sleep(0.05)
            if orch.status.cycles >= 1 and orch.status.state == "idle":
                break
        assert orch.status.cycles >= 1
        with ctx.db.session() as s:
            assert all(
                a.status == "done"
                for a in SchedulerService(s).list()
                if a.action_type == "manager_reevaluate" and a.scheduled_at < iso_in()
            )
            assert SchedulerService(s).pending(action_type="manager_reevaluate")
        status = orch.status_dict()
        assert status["state"] in ("idle", "running") and status["next_scheduled_at"]
    finally:
        await orch.stop()
    assert orch.status.state == "stopped"
