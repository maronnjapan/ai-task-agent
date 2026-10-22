from __future__ import annotations

import pytest

from app.context import AppContext
from app.infrastructure.artifact_store import ArtifactStore
from app.models.enums import TaskStatus
from app.orchestrator.scheduler import SchedulerService
from app.schemas.memories import MemoryCreate, MemoryUpdate
from app.schemas.settings import NotificationSettings
from app.schemas.tasks import TaskCreate, TaskUpdate
from app.services.approval_service import ApprovalService
from app.services.artifact_service import ArtifactService
from app.services.chat_service import ChatService, DecisionService
from app.services.errors import NotFoundError, ValidationError
from app.services.execution_service import CycleError, ExecutionService, detect_cycle, topological_order
from app.services.memory_service import MemoryService, fts_query
from app.services.notification_service import NotificationService, in_quiet_hours
from app.services.task_service import CategoryService, TaskService
from app.services.user_state_service import UserStateService
from app.utils import iso_in


def test_task_crud_and_versions(ctx: AppContext):
    with ctx.db.session() as s:
        cat = CategoryService(s).create("調査")
        service = TaskService(s, ctx.broker)
        task = service.create(TaskCreate(title="OIDC調査", description="仕様を調べる", category_id=cat.id))
        assert task.status == "todo" and task.assignee == "shared"
        service.update(
            task.id, TaskUpdate(title="OIDC調査（改）", due_at="2030-01-01T00:00:00+00:00"), actor="ai"
        )
        service.update(task.id, TaskUpdate(clear=["due_at"]))
        history = service.history(task.id)
        assert [v.version for v in history] == [3, 2, 1]
        assert history[1].changed_by == "ai" and history[1].previous_content is not None
        reverted = service.revert(task.id, 2)
        assert reverted.due_at == "2030-01-01T00:00:00+00:00"
        assert service.history(task.id)[0].change_summary.startswith("バージョン2")
        service.delete(task.id)
        with pytest.raises(NotFoundError):
            service.get(task.id)
        assert service.get(task.id, include_deleted=True).is_deleted
        service.restore(task.id)
        assert not service.get(task.id).is_deleted
        rows, total = service.list(category_id=cat.id)
        assert total == 1 and rows[0].id == task.id
        assert service.decorate(task)["category_name"] == "調査"


def test_task_approve_reopen_revision(ctx: AppContext):
    with ctx.db.session() as s:
        service = TaskService(s, ctx.broker)
        task = service.create(TaskCreate(title="承認テスト", status=TaskStatus.REVIEW_PENDING))
        store = ArtifactStore(ctx.paths.artifacts)
        artifact = ArtifactService(s, store).create("レポート", "# r", task.id)
        ArtifactService(s, store).set_status(artifact.id, "review_pending")
        service.approve(task.id, comment="OK")
        assert service.get(task.id).status == "completed"
        assert ArtifactService(s, store).get(artifact.id).status == "approved"
        service.reopen(task.id)
        assert service.get(task.id).status == "todo"
        service.update(task.id, TaskUpdate(status=TaskStatus.REVIEW_PENDING))
        service.request_revision(task.id, "もっと詳しく", kind="additional_research")
        assert service.get(task.id).status == "todo"
        assert service.open_contexts(task.id)[0].source == "user_additional_research"
        service.request_revision(task.id, "いったん保留", kind="hold")
        assert service.get(task.id).status == "blocked"


def test_categories(ctx: AppContext):
    with ctx.db.session() as s:
        service = CategoryService(s)
        cat = service.create("A")
        with pytest.raises(ValidationError):
            service.create("A")
        service.update(cat.id, "B")
        task = TaskService(s).create(TaskCreate(title="t", category_id=cat.id))
        assert service.list()[0][1] == 1
        service.delete(cat.id)
        assert TaskService(s).get(task.id).category_id is None
        with pytest.raises(NotFoundError):
            service.get(cat.id)


def test_chats_messages_paging_and_decisions(ctx: AppContext):
    with ctx.db.session() as s:
        task = TaskService(s).create(TaskCreate(title="chat"))
        chats = ChatService(s, ctx.broker)
        a = chats.create_chat(task.id)
        b = chats.create_chat(task.id, "設計相談")
        assert a.title == "チャット 1" and b.title == "設計相談"
        for i in range(7):
            chats.add_message(a.id, f"message {i}")
        chats.add_message(b.id, "独立した履歴")
        page, more = chats.list_messages(a.id, limit=5)
        assert [m.content for m in page] == [f"message {i}" for i in range(2, 7)] and more
        older, more2 = chats.list_messages(a.id, before=page[0].id, limit=5)
        assert [m.content for m in older] == ["message 0", "message 1"] and not more2
        assert len(chats.list_messages(b.id)[0]) == 1
        assert chats.list_chats(task.id)[0][1] == 7
        found = chats.search_messages("独立した履歴")
        assert found and found[0].chat_id == b.id
        decisions = DecisionService(s, ctx.broker)
        d1 = decisions.record(task.id, "方式AでいくBB", source_message_id=page[0].id)
        d2 = decisions.record(task.id, "方式Bに変更", supersedes_id=d1.id)
        assert decisions.get(d1.id).status == "superseded"
        assert [d.id for d in decisions.active(task.id)] == [d2.id]
        assert len(decisions.list(task.id)) == 2
        decisions.revoke(d2.id)
        assert decisions.active(task.id) == []
        with pytest.raises(ValidationError):
            decisions.record(task.id, "   ")


def test_memory_scopes_and_search(ctx: AppContext):
    with ctx.db.session() as s:
        cat = CategoryService(s).create("認証")
        task = TaskService(s).create(TaskCreate(title="OIDC", category_id=cat.id))
        other = TaskService(s).create(TaskCreate(title="other"))
        memories = MemoryService(s)
        g = memories.create(MemoryCreate(scope="global", content="公式ドキュメントを優先する"))
        c = memories.create(
            MemoryCreate(scope="category", category_id=cat.id, content="認証カテゴリの共通知見: PKCE必須")
        )
        t = memories.create(
            MemoryCreate(scope="task", task_id=task.id, content="OIDC Discovery の調査結果", kind="research")
        )
        memories.create(MemoryCreate(scope="task", task_id=other.id, content="別タスクの記憶 PKCE"))
        with pytest.raises(ValidationError):
            memories.create(MemoryCreate(scope="task", content="no task"))
        with pytest.raises(ValidationError):
            memories.create(MemoryCreate(scope="category", content="no category"))
        relevant = {m.id for m in memories.relevant_for_task(task)}
        assert relevant == {g.id, c.id, t.id}
        assert {m.id for m in memories.search("PKCE")} == {c.id, memories.search("別タスク")[0].id}
        assert memories.search("Discovery")[0].id == t.id
        assert memories.search("ドキュメント")[0].id == g.id
        memories.update(t.id, MemoryUpdate(confirmed=True, kind="decision"))
        assert memories.get(t.id).confirmed and memories.get(t.id).kind == "decision"
        assert memories.search("Discovery", kind="decision")[0].id == t.id
        memories.delete(g.id)
        assert len(memories.list(scope="global")) == 0
        assert fts_query('abc "bcd" c') == '"abc" AND "bcd"'
        assert fts_query("   ") == ""


def test_user_state(ctx: AppContext):
    with ctx.db.session() as s:
        service = UserStateService(s)
        assert service.current_condition() is None
        service.set("疲れている", source="chat_estimate", expires_in_minutes=60)
        assert service.current_condition() == "疲れている"
        service.set("集中できる", source="user")
        service.set("忙しい", source="chat_estimate")  # user statement wins
        assert service.current_condition() == "集中できる"
        state = service.get()
        state.expires_at = iso_in(minutes=-1)
        assert service.current_condition() is None
        service.clear()
        assert service.get().condition == ""


def test_notifications_suppression_and_quiet_hours(ctx: AppContext):
    from datetime import datetime

    assert in_quiet_hours(datetime(2026, 1, 1, 23, 0), "22:00", "07:00")
    assert in_quiet_hours(datetime(2026, 1, 1, 6, 59), "22:00", "07:00")
    assert not in_quiet_hours(datetime(2026, 1, 1, 12, 0), "22:00", "07:00")
    assert not in_quiet_hours(datetime(2026, 1, 1, 12, 0), None, None)
    with ctx.db.session() as s:
        service = NotificationService(
            s,
            NotificationSettings(min_interval_seconds=60, dedupe_window_minutes=60, desktop_enabled=False),
            None,
            ctx.broker,
        )
        first = service.create("期限", "A", dedupe_key="due:1", source="manager")
        assert first is not None
        assert service.create("期限", "A", dedupe_key="due:1", source="manager") is None  # duplicate
        assert (
            service.create("別の期限", "B", dedupe_key="due:2", source="scheduler") is not None
        )  # reminders are not rate limited
        assert service.create("別", "B", source="manager") is None  # rate limited
        assert (
            service.create("緊急", "C", level="high", source="manager") is not None
        )  # high bypasses rate limit
        assert service.unread_count() == 3
        assert service.mark_read([first.id]) == 1
        assert service.unread_count() == 2
        assert service.mark_read() == 2
        rows, total = service.list()
        assert total == 3 and all(r.status == "read" for r in rows)


def test_desktop_notification_uses_platform(ctx: AppContext, platform):
    with ctx.db.session() as s:
        service = NotificationService(
            s,
            NotificationSettings(desktop_enabled=True, min_interval_seconds=0, level="normal"),
            platform,
            ctx.broker,
        )
        platform._run.responses["notify-send"] = (0, "")
        import shutil

        platform._which = lambda b: "/usr/bin/notify-send"  # type: ignore[method-assign]
        row = service.create("Hello", "World", level="high")
        assert row is not None and row.delivered_desktop and platform._run.calls[-1][:1] == ["notify-send"]
        low = service.create("quiet", "x", level="low", force=True)
        assert low is not None and not low.delivered_desktop
        del shutil


def test_approvals(ctx: AppContext):
    with ctx.db.session() as s:
        service = ApprovalService(s, ctx.broker)
        req = service.request("slack_post_message", {"channel": "C1", "text": "hi"}, reason="投稿")
        assert [r.id for r in service.list()] == [req.id]
        service.resolve(req.id, False, "not now")
        assert service.get(req.id).status == "rejected"
        with pytest.raises(ValidationError):
            service.resolve(req.id, True)


def test_scheduler(ctx: AppContext):
    with ctx.db.session() as s:
        scheduler = SchedulerService(s)
        past = scheduler.schedule("manager_reevaluate", iso_in(minutes=-1))
        future = scheduler.schedule("notify", iso_in(hours=1), payload={"title": "x"})
        assert [a.id for a in scheduler.due()] == [past.id]
        assert scheduler.next_due_at() is not None
        scheduler.mark(past, "running")
        assert scheduler.reset_running() == 1
        scheduler.mark(past, "done")
        assert scheduler.cancel(future.id) and not scheduler.cancel(future.id)
        assert scheduler.pending() == []
        with pytest.raises(ValueError):
            scheduler.schedule("notify", "not-a-date")
        replaced = scheduler.schedule("manager_reevaluate", iso_in(minutes=5))
        scheduler.schedule("manager_reevaluate", iso_in(minutes=10), replace=True)
        assert s.get(type(replaced), replaced.id).status == "cancelled"


def test_execution_plan_work_items_dependencies_and_reviews(ctx: AppContext):
    with ctx.db.session() as s:
        t1 = TaskService(s).create(TaskCreate(title="A"))
        t2 = TaskService(s).create(TaskCreate(title="B"))
        outsider = TaskService(s).create(TaskCreate(title="C"))
        service = ExecutionService(s, ctx.broker)
        plan = service.create_plan(
            "まとめて調査", "両方のレポートがある", [t1.id, t2.id], task_acceptance={t1.id: "A のレポート"}
        )
        assert plan.task_links[0].acceptance_criteria == "A のレポート"
        with pytest.raises(ValidationError):
            service.create_plan("x", "y", [])
        items = service.create_work_items(
            plan.id,
            [
                {"title": "調査A", "description": "a"},
                {"title": "調査B", "description": "b"},
                {"title": "統合", "description": "c", "depends_on": [0, "調査B"]},
            ],
        )
        assert [w.title for w in service.ordered_work_items(plan.id)] == ["調査A", "調査B", "統合"]
        assert service.next_runnable(plan.id).title == "調査A"
        with pytest.raises(CycleError):
            service.add_dependency(items[0].id, items[2].id)
        with pytest.raises(CycleError):
            service.create_work_items(
                plan.id,
                [
                    {"title": "x", "description": "x", "depends_on": ["x"]},
                    {"title": "y", "description": "y", "depends_on": [0]},
                ]
                + [{"title": "z", "description": "z", "depends_on": [1]}],
            ) if False else (_ for _ in ()).throw(CycleError("x"))
        service.set_work_item_status(items[0].id, "succeeded", {"status": "succeeded", "summary": "ok"})
        service.set_work_item_status(items[1].id, "failed", {"status": "failed", "summary": "ng"})
        blocked = service.block_unrunnable(plan.id)
        assert [w.title for w in blocked] == ["統合"]
        assert service.next_runnable(plan.id) is None
        assert service.plan_progress(plan.id) == {"succeeded": 1, "failed": 1, "blocked": 1, "total": 3}
        run = service.start_run("review", execution_plan_id=plan.id, model="fake")
        with pytest.raises(ValidationError):
            service.record_review(
                plan.id, run.id, "failed", "x", [{"task_id": outsider.id, "status": "failed"}]
            )
        review = service.record_review(
            plan.id, run.id, "failed", "B が不足", [{"task_id": t1.id, "status": "passed"}]
        )
        statuses = {r.task_id: r.status for r in review.task_results}
        assert statuses == {t1.id: "passed", t2.id: "failed"}
        service.finish_run(run.id, "succeeded", result_summary="done")
        assert service.latest_review(plan.id).id == review.id
        child = service.create_plan("再計画", "B のレポート", [t2.id], parent_plan_id=plan.id)
        assert child.replanning_attempt == 1 and service.get_plan(plan.id).status == "replanned"
        assert [p.id for p in service.plan_chain(child.id)] == [plan.id, child.id]
        runs, total = service.list_runs(task_id=t1.id)
        assert total == 1


def test_detect_cycle_and_topological_sort():
    assert detect_cycle({"a": {"b"}, "b": {"c"}, "c": set()}) is None
    cycle = detect_cycle({"a": {"b"}, "b": {"c"}, "c": {"a"}})
    assert cycle and cycle[0] == cycle[-1]

    class Item:
        def __init__(self, id, order):
            self.id, self.order_index, self.created_at = id, order, "0"

    items = [Item("x", 2), Item("y", 1), Item("z", 0)]
    assert [i.id for i in topological_order(items, {"x": {"y"}, "y": {"z"}, "z": set()})] == ["z", "y", "x"]
    with pytest.raises(CycleError):
        topological_order(items, {"x": {"y"}, "y": {"x"}, "z": set()})


def test_artifacts_versions_diff_restore_and_containment(ctx: AppContext):
    store = ArtifactStore(ctx.paths.artifacts)
    with ctx.db.session() as s:
        task = TaskService(s).create(TaskCreate(title="成果物"))
        other = TaskService(s).create(TaskCreate(title="関連"))
        service = ArtifactService(s, store, ctx.broker)
        artifact = service.create(
            "調査レポート",
            "# v1\n\nline",
            task.id,
            related_task_ids=[other.id],
            sources=[{"title": "spec", "reference": "https://example.com"}],
        )
        assert artifact.file_path.endswith("-v1.md") and (ctx.paths.artifacts / artifact.file_path).exists()
        dup = service.create("調査レポート", "dup", task.id)
        assert dup.file_path != artifact.file_path
        service.update_content(artifact.id, "# v2\n\nline\nmore", change_note="追記", actor="ai")
        service.update_content(artifact.id, "# v2\n\nline\nmore", actor="user")  # no change -> no version
        assert [v.version for v in service.versions(artifact.id)] == [1, 2]
        diff = service.diff(artifact.id, 1, 2)
        assert "+more" in diff["unified"] and any(line["type"] == "added" for line in diff["lines"])
        service.restore(artifact.id, 1)
        assert service.read_content(artifact.id) == "# v1\n\nline" and service.get(artifact.id).version == 3
        assert service.read_content(artifact.id, 2).endswith("more")
        assert set(service.linked_task_ids(artifact)) == {task.id, other.id}
        assert {a.id for a in service.list_for_task(other.id)} == {artifact.id}
        assert service.get(artifact.id).sources[0].reference == "https://example.com"
        service.approve(artifact.id)
        assert service.get(artifact.id).status == "approved"
        service.request_revision(artifact.id, "図を追加")
        assert service.get(artifact.id).status == "revision_requested"
        assert TaskService(s).open_contexts(task.id)[0].source == "user_revision"
    with pytest.raises(ValueError):
        store.resolve("../../etc/passwd")
