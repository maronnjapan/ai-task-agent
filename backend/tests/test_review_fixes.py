"""Regression tests for the issues found by the SPEC compliance review."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from app.context import AppContext
from app.integrations.local_files import LocalFileSource
from app.integrations.mcp.client import MCPUnauthorized, is_unauthorized
from app.integrations.mcp.config import SECRET_PLACEHOLDER, ConnectionConfig
from app.integrations.mcp.registry import MCPRegistry
from app.integrations.permissions import classify_tool
from app.models import AgentRun, Notification, WorkItem
from app.orchestrator.event_queue import Trigger
from app.orchestrator.runner import Orchestrator
from app.orchestrator.scheduler import SchedulerService
from app.schemas.integrations import IntegrationCreate, IntegrationUpdate
from app.schemas.memories import MemoryCreate
from app.schemas.settings import LocalSourceSettings, NotificationSettings
from app.schemas.tasks import TaskCreate, TaskUpdate
from app.services.approval_service import ApprovalService
from app.services.artifact_service import ArtifactService
from app.services.execution_service import ExecutionService
from app.services.integration_service import IntegrationService
from app.services.memory_service import MemoryService
from app.services.notification_service import NotificationService
from app.services.task_service import CategoryService, TaskService
from app.utils import iso_in
from tests.conftest import tool_call
from tests.test_workflow import make_tasks, plan_script, review_script, worker_success

SERVER = Path(__file__).parent / "mcp_test_server.py"


def test_due_dates_and_schedules_are_normalised_to_utc(ctx: AppContext):
    with ctx.db.session() as s:
        task = TaskService(s).create(TaskCreate(title="t", due_at="2030-01-01T09:00:00+09:00"))
        assert task.due_at == "2030-01-01T00:00:00+00:00"
        TaskService(s).update(task.id, TaskUpdate(due_at="2030-01-02T00:00:00Z"))
        assert TaskService(s).get(task.id).due_at == "2030-01-02T00:00:00+00:00"
        action = SchedulerService(s).schedule("notify", "2030-01-01T09:00:00+09:00")
        assert action.scheduled_at == "2030-01-01T00:00:00+00:00"
        from app.services.errors import ValidationError

        with pytest.raises(ValidationError):
            TaskService(s).create(TaskCreate(title="bad", due_at="not a date"))


def test_category_delete_keeps_task_memories(ctx: AppContext):
    with ctx.db.session() as s:
        cat = CategoryService(s).create("認証")
        task = TaskService(s).create(TaskCreate(title="t", category_id=cat.id))
        task_memory = MemoryService(s).create(
            MemoryCreate(scope="task", task_id=task.id, content="task memory")
        )
        MemoryService(s).create(MemoryCreate(scope="category", category_id=cat.id, content="category memory"))
        CategoryService(s).delete(cat.id)
        kept = MemoryService(s).get(task_memory.id)
        assert kept.category_id is None and kept.task_id == task.id
        assert MemoryService(s).list(scope="category") == []


def test_memory_search_filters_fall_back_to_substring_match(ctx: AppContext):
    with ctx.db.session() as s:
        a = TaskService(s).create(TaskCreate(title="A"))
        b = TaskService(s).create(TaskCreate(title="B"))
        MemoryService(s).create(MemoryCreate(scope="task", task_id=a.id, content="OIDC Discovery endpoint"))
        hit = MemoryService(s).create(
            MemoryCreate(scope="task", task_id=b.id, content="OIDC Discovery for B")
        )
        # FTS ranks A's memory first; filtering by task B must still return B's memory
        assert [m.id for m in MemoryService(s).search("Discovery", task_id=b.id)] == [hit.id]
        for i in range(25):
            MemoryService(s).create(MemoryCreate(scope="task", task_id=a.id, content=f"filler memory {i}"))
        relevant = MemoryService(s).relevant_for_task(
            TaskService(s).get(a).id if False else TaskService(s).get(a.id), query="Discovery", limit=5
        )
        assert relevant[0].content == "OIDC Discovery endpoint"  # query matches are never cut off by recency


def test_hold_blocks_manager_planning(ctx: AppContext):
    from app.agents.context import AgentContext
    from app.agents.tools.manager_tools import build_manager_tools

    (task_id,) = make_tasks(ctx, "保留中")
    with ctx.db.session() as s:
        TaskService(s).request_revision(task_id, "一旦保留", kind="hold")
        assert TaskService(s).is_on_hold(task_id)
    tools = {
        t.name: t for t in build_manager_tools(AgentContext(app=ctx, agent_type="manager", mode="evaluate"))
    }
    assert "on hold" in tools["create_execution_plan"].invoke(
        {"objective": "o", "acceptance_criteria": "c", "task_ids": [task_id]}
    )
    assert '"on_hold": true' in tools["list_tasks"].invoke({"status": "blocked"})
    with ctx.db.session() as s:
        TaskService(s).reopen(task_id)
        assert not TaskService(s).is_on_hold(task_id)


@pytest.mark.asyncio
async def test_malformed_review_verdict_never_leaves_plan_stuck(ctx: AppContext, models):
    (a,) = make_tasks(ctx, "A")
    models["manager"].push(*plan_script([a], [{"title": "w", "description": "w"}]))
    models["worker"].push(*worker_success())
    models["review"].push(
        tool_call(
            "submit_review",
            status="passed",
            feedback="ok",
            task_results=[{"task_id": "not-a-task", "status": "weird"}, {"task_id": a, "status": "PASSED"}],
        ),
        {"content": "done"},
    )
    orch = Orchestrator(ctx)
    await orch.run_cycle([Trigger("manual_run")])
    with ctx.db.session() as s:
        plan = ExecutionService(s).list_plans()[0][0]
        assert plan.status == "passed"
        review = ExecutionService(s).latest_review(plan.id)
        assert {r.task_id: r.status for r in review.task_results} == {a: "passed"}
        assert TaskService(s).get(a).status == "review_pending"


@pytest.mark.asyncio
async def test_review_crash_is_recorded_as_failed_run(ctx: AppContext, models):
    (a,) = make_tasks(ctx, "A")
    models["manager"].push(*plan_script([a], [{"title": "w", "description": "w"}]))
    models["worker"].push(*worker_success())

    def boom(messages):
        raise RuntimeError("review model down")

    models["review"].push(boom)
    models["manager"].push({"content": "再計画しません"})
    await Orchestrator(ctx).run_cycle([Trigger("manual_run")])
    with ctx.db.session() as s:
        runs = [r for r in s.execute(select(AgentRun)).scalars() if r.agent_type == "review"]
        assert runs and runs[0].status == "failed" and "review model down" in (runs[0].error_message or "")
        assert ExecutionService(s).list_plans()[0][0].status != "reviewing"


@pytest.mark.asyncio
async def test_per_task_failure_overrides_overall_pass_and_uncovered_tasks_stop(ctx: AppContext, models):
    a, b, c = make_tasks(ctx, "A", "B", "C")
    models["manager"].push(*plan_script([a, b], [{"title": "w", "description": "w"}]))
    models["worker"].push(*worker_success())
    models["review"].push(*review_script({a: "passed", b: "failed"}, status="passed"))  # inconsistent verdict
    models["manager"].push(
        *plan_script([c], [{"title": "再試行", "description": "C だけ"}], objective="別タスクの計画")
    )  # replans the wrong task
    models["worker"].push(*worker_success())
    models["review"].push(*review_script({c: "passed"}))
    await Orchestrator(ctx).run_cycle([Trigger("manual_run")])
    with ctx.db.session() as s:
        plans = {p.replanning_attempt: p for p in ExecutionService(s).list_plans()[0]}
        assert plans[0].status == "replanned" and plans[1].status == "passed"
        assert TaskService(s).get(a).status == "review_pending"
        assert TaskService(s).get(b).status == "blocked"  # failed but not covered by the new plan
        contexts = TaskService(s).open_contexts(b)
        assert any(c.source == "retry_exhausted" for c in contexts)
        skipped = [i for i in s.execute(select(WorkItem)).scalars() if i.status == "skipped"]
        assert skipped == []  # all items of the first plan had run


@pytest.mark.asyncio
async def test_replanning_skips_unfinished_items_of_the_old_plan(ctx: AppContext):
    (a,) = make_tasks(ctx, "A")
    with ctx.db.session() as s:
        service = ExecutionService(s)
        plan = service.create_plan("o", "c", [a])
        items = service.create_work_items(
            plan.id,
            [{"title": "x", "description": "x"}, {"title": "y", "description": "y", "depends_on": [0]}],
        )
        service.set_work_item_status(items[0].id, "failed", {"status": "failed", "summary": "ng"})
        service.block_unrunnable(plan.id)
        service.set_plan_status(plan.id, "failed")
        service.create_plan("retry", "c", [a], parent_plan_id=plan.id)
        assert service.get_work_item(items[1].id).status == "skipped"
        assert service.get_plan(plan.id).status == "replanned"


@pytest.mark.asyncio
async def test_no_progress_limit_is_persisted_and_notified(ctx: AppContext, models):
    make_tasks(ctx, "idle")
    models["manager"].push({"content": "nothing"}, {"content": "nothing"})
    orch = Orchestrator(ctx)
    await orch.run_cycle([Trigger("reevaluate")])
    await orch.run_cycle([Trigger("reevaluate")])
    await orch.run_cycle([Trigger("reevaluate")])  # limit reached -> skipped and reported
    fresh = Orchestrator(ctx)
    await fresh.start()
    try:
        assert fresh.status.consecutive_no_progress >= 2  # restored from SQLite
    finally:
        await fresh.stop()
    with ctx.db.session() as s:
        titles = [n.title for n in s.execute(select(Notification)).scalars()]
        assert "AI の自動再評価を一時停止しました" in titles
        assert "Manager AI からの返答" not in titles


@pytest.mark.asyncio
async def test_instruction_response_is_stored_as_manager_message(ctx: AppContext, models):
    (a,) = make_tasks(ctx, "A")
    models["manager"].push({"content": "タスク A は明日着手します"})
    orch = Orchestrator(ctx)
    result = await orch.run_instruction("A の予定を教えて", [a])
    assert result.text
    with ctx.db.session() as s:
        row = (
            s.execute(select(Notification).where(Notification.channel == "manager_message")).scalars().first()
        )
        assert (
            row is not None
            and row.body == "タスク A は明日着手します"
            and row.task_id == a
            and not row.delivered_desktop
        )


def test_notifications_daily_dedupe_and_quiet_hours(ctx: AppContext, platform):
    with ctx.db.session() as s:
        platform._which = lambda b: "/usr/bin/notify-send"  # type: ignore[method-assign]
        quiet = NotificationService(
            s,
            NotificationSettings(
                desktop_enabled=True,
                min_interval_seconds=0,
                quiet_hours_start="00:00",
                quiet_hours_end="23:59",
            ),
            platform,
            ctx.broker,
        )
        row = quiet.create("night", "x", level="high", force=True)
        assert row is not None and not row.delivered_desktop  # quiet hours apply to every level
        events = [e for e in ctx.broker.history() if e.type == "notification.created"]
        assert events[-1].data["quiet"] is True
        service = NotificationService(
            s,
            NotificationSettings(desktop_enabled=False, min_interval_seconds=0, dedupe_window_minutes=1),
            None,
            ctx.broker,
        )
        assert (
            service.create("due", "x", dedupe_key="due:1:today", source="scheduler", dedupe_minutes=24 * 60)
            is not None
        )
        assert (
            service.create("due", "x", dedupe_key="due:1:today", source="scheduler", dedupe_minutes=24 * 60)
            is None
        )
        # Manager messages never count toward the rate limit
        rate = NotificationService(
            s, NotificationSettings(desktop_enabled=False, min_interval_seconds=60), None, ctx.broker
        )
        assert rate.create("msg", "x", source="manager", channel="manager_message", force=True) is not None
        assert rate.create("alert", "x", source="manager") is not None


def test_integration_secret_env_and_headers_go_to_secret_provider(ctx: AppContext):
    with ctx.db.session() as s:
        service = IntegrationService(s, ctx.secret_store)
        row = service.create(
            IntegrationCreate(
                name="slack",
                adapter="slack",
                transport="stdio",
                command="npx",
                env={"SLACK_BOT_TOKEN": "xoxb-secret-value", "SLACK_TEAM_ID": "T123"},
                headers={"Authorization": "Bearer abc", "X-Trace": "1"},
            )
        )
        config = ConnectionConfig.from_model(row)
        assert config.env == {"SLACK_BOT_TOKEN": SECRET_PLACEHOLDER, "SLACK_TEAM_ID": "T123"}
        assert config.headers == {"Authorization": SECRET_PLACEHOLDER, "X-Trace": "1"}
        assert (
            "xoxb-secret-value" not in row.env
            and ctx.secret_store.get_secret(config.env_secret_name("SLACK_BOT_TOKEN")) == "xoxb-secret-value"
        )
        resolved = ConnectionConfig.from_model(row).resolve_secrets(ctx.secret_store)
        assert (
            resolved.env["SLACK_BOT_TOKEN"] == "xoxb-secret-value"
            and resolved.headers["Authorization"] == "Bearer abc"
        )
        # re-saving the placeholder keeps the secret; an empty value deletes it
        service.update(
            row.id, IntegrationUpdate(env={"SLACK_BOT_TOKEN": SECRET_PLACEHOLDER, "SLACK_TEAM_ID": "T999"})
        )
        assert (
            ConnectionConfig.from_model(row).resolve_secrets(ctx.secret_store).env["SLACK_BOT_TOKEN"]
            == "xoxb-secret-value"
        )
        service.update(row.id, IntegrationUpdate(env={"SLACK_BOT_TOKEN": ""}))
        assert ctx.secret_store.get_secret(config.env_secret_name("SLACK_BOT_TOKEN")) is None
        registry = MCPRegistry(ctx)
        assert registry.redirect_uri().endswith(f":{ctx.settings.app_port}/api/integrations/oauth/callback")


def test_unknown_tools_fail_closed_and_unauthorized_detection():
    assert classify_tool("do_something_opaque") == "external_write"
    assert classify_tool("weather", "Get the current weather") == "read"
    assert classify_tool("search_messages") == "read"
    assert is_unauthorized(RuntimeError("HTTP 401 Unauthorized"))
    assert is_unauthorized(MCPUnauthorized("x"))
    assert not is_unauthorized(RuntimeError("item 4013 not found"))
    assert not is_unauthorized(RuntimeError("tool failure for tests"))


@pytest.mark.asyncio
async def test_pre_approved_external_write_executes_once(ctx: AppContext):
    registry = MCPRegistry(ctx, approval_wait_seconds=0.0)
    with ctx.db.session() as s:
        row = IntegrationService(s, ctx.secret_store).create(
            IntegrationCreate(name="pre", transport="stdio", command=sys.executable, args=[str(SERVER)])
        )
        approved = ApprovalService(s).request(
            "post_message", {"channel": "C1", "text": "hi"}, connection_id=row.id
        )
        ApprovalService(s).resolve(approved.id, True)
    try:
        result = await registry.call_tool(row.id, "post_message", {"channel": "C1", "text": "hi"})
        assert "posted to C1" in result.text
        with ctx.db.session() as s:
            assert ApprovalService(s).get(approved.id).executed_at is not None
            assert [n.title for n in s.execute(select(Notification)).scalars()] == []
        from app.integrations.mcp.registry import ApprovalPendingError

        with pytest.raises(ApprovalPendingError):  # consumed approvals are not reused
            await registry.call_tool(row.id, "post_message", {"channel": "C1", "text": "hi"})
        with ctx.db.session() as s:
            assert any(
                n.title == "外部操作の承認が必要です" for n in s.execute(select(Notification)).scalars()
            )
    finally:
        await registry.shutdown()


@pytest.mark.asyncio
async def test_approval_resumes_blocked_work_item(ctx: AppContext, models):
    (a,) = make_tasks(ctx, "A")
    with ctx.db.session() as s:
        service = ExecutionService(s)
        plan = service.create_plan("o", "c", [a])
        item = service.create_work_items(plan.id, [{"title": "post", "description": "post"}])[0]
        service.set_work_item_status(
            item.id, "blocked", {"status": "blocked", "summary": "approval required"}
        )
        service.set_plan_status(plan.id, "blocked")
        TaskService(s).set_status(a, "blocked")
        request = ApprovalService(s).request("post_message", {"text": "hi"}, work_item_id=item.id, task_id=a)
        ApprovalService(s).resolve(request.id, True)
    models["worker"].push(*worker_success())
    models["review"].push(*review_script({a: "passed"}))
    models["manager"].push({"content": "nothing"})
    orch = Orchestrator(ctx)
    await orch.run_cycle([Trigger("approval_resolved", {"approval_id": request.id, "status": "approved"})])
    with ctx.db.session() as s:
        assert ExecutionService(s).get_work_item(item.id).status == "succeeded"
        assert TaskService(s).get(a).status == "review_pending"


def test_local_files_skip_symlinks_outside_roots(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    (tmp_path / "secret.md").write_text("OIDC secret outside", encoding="utf-8")
    (root / "inside.md").write_text("OIDC inside", encoding="utf-8")
    os.symlink(tmp_path / "secret.md", root / "link.md")
    source = LocalFileSource(LocalSourceSettings(directories=[str(root)], extensions=[".md"]))
    assert [h.path for h in source.search("OIDC")] == [str(root / "inside.md")]


def test_artifact_revision_only_reopens_review_pending_tasks(ctx: AppContext):
    from app.infrastructure.artifact_store import ArtifactStore

    with ctx.db.session() as s:
        primary = TaskService(s).create(TaskCreate(title="primary", status="review_pending"))
        other = TaskService(s).create(TaskCreate(title="other", status="in_progress"))
        service = ArtifactService(s, ArtifactStore(ctx.paths.artifacts), ctx.broker)
        artifact = service.create("report", "# r", primary.id, related_task_ids=[other.id])
        service.request_revision(artifact.id, "図を追加")
        assert TaskService(s).get(primary.id).status == "todo"
        assert TaskService(s).get(other.id).status == "in_progress"
        assert len(TaskService(s).open_contexts(primary.id)) == 1
        assert len(TaskService(s).open_contexts(other.id)) == 1


def test_settings_snapshot_and_session_token_file(ctx: AppContext, client):
    import json

    snapshot = json.loads(ctx.paths.settings_file.read_text())
    assert snapshot["manager"]["autonomy_level"] == "balanced"
    client.patch("/api/settings", json={"manager": {**snapshot["manager"], "autonomy_level": "proactive"}})
    assert json.loads(ctx.paths.settings_file.read_text())["manager"]["autonomy_level"] == "proactive"
    token_file = ctx.paths.config / "session.token"
    assert token_file.exists() and (os.name == "nt" or oct(token_file.stat().st_mode)[-3:] == "600")


def test_scheduled_reminder_fires_once_per_day(ctx: AppContext, models):
    import asyncio

    with ctx.db.session() as s:
        TaskService(s).create(TaskCreate(title="soon", due_at=iso_in(hours=1)))
    models["manager"].push({"content": "n"}, {"content": "n"})
    orch = Orchestrator(ctx)
    asyncio.run(orch.run_cycle([Trigger("manual_run")]))
    with ctx.db.session() as s:
        NotificationService(s).mark_read()
    asyncio.run(orch.run_cycle([Trigger("manual_run")]))
    with ctx.db.session() as s:
        due = [n for n in s.execute(select(Notification)).scalars() if n.title == "期限が近づいています"]
        assert len(due) == 1
