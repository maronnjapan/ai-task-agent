"""AI workflow tests (SPEC 30.2) driven by scripted LLMs through the real orchestrator."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.context import AppContext
from app.models import AgentRun, Notification, TaskContext
from app.orchestrator.event_queue import Trigger
from app.orchestrator.runner import Orchestrator
from app.schemas.tasks import TaskCreate
from app.services.artifact_service import ArtifactService
from app.services.execution_service import ExecutionService
from app.services.task_service import TaskService
from tests.conftest import last_tool_json, tool_call


def make_tasks(ctx: AppContext, *titles: str, assignee: str = "ai") -> list[str]:
    ids = []
    with ctx.db.session() as s:
        for title in titles:
            ids.append(TaskService(s).create(TaskCreate(title=title, assignee=assignee)).id)
    return ids


def plan_script(
    task_ids: list[str],
    items: list[dict],
    objective: str = "まとめて調査する",
    text: str = "計画を作成しました",
):
    """Manager script: create a plan for ``task_ids`` then its work items."""

    def create_items(messages):
        payload = last_tool_json(messages)
        if not isinstance(payload, dict) or "plan_id" not in payload:
            return {"content": f"計画を作成できませんでした: {payload}"}
        return tool_call("create_work_items", plan_id=payload["plan_id"], items=items)

    return [
        tool_call(
            "create_execution_plan",
            objective=objective,
            acceptance_criteria="各タスクのレポートが Markdown で存在する",
            task_ids=task_ids,
            task_acceptance_criteria={t: f"{t[:4]} のレポート" for t in task_ids},
        ),
        create_items,
        {"content": text},
    ]


def worker_success(
    title: str = "調査レポート", content: str = "# レポート\n\n調査結果", with_artifact: bool = True
):
    script = []
    if with_artifact:
        script.append(
            tool_call(
                "create_markdown_artifact",
                title=title,
                content=content,
                sources=[{"title": "spec", "reference": "https://example.com/spec", "source_type": "web"}],
            )
        )
    script.append(
        tool_call(
            "report_work_result",
            status="succeeded",
            summary=f"{title} を作成",
            sources=[{"title": "spec", "reference": "https://example.com/spec"}],
        )
    )
    script.append({"content": "完了"})
    return script


def review_script(
    results: dict[str, str], status: str | None = None, feedback: str = "完了条件を満たしています"
):
    overall = status or (
        "passed"
        if all(v == "passed" for v in results.values())
        else ("blocked" if any(v == "blocked" for v in results.values()) else "failed")
    )
    return [
        tool_call(
            "submit_review",
            status=overall,
            feedback=feedback,
            task_results=[
                {"task_id": t, "status": s, "feedback": None if s == "passed" else feedback}
                for t, s in results.items()
            ],
        ),
        {"content": "レビュー完了"},
    ]


def orchestrator(ctx: AppContext) -> Orchestrator:
    return Orchestrator(ctx)


def task_status(ctx: AppContext, task_id: str) -> str:
    with ctx.db.session() as s:
        return TaskService(s).get(task_id).status


def notifications(ctx: AppContext) -> list[Notification]:
    with ctx.db.session() as s:
        return list(s.execute(select(Notification).order_by(Notification.created_at)).scalars())


@pytest.mark.asyncio
async def test_full_cycle_multi_task_plan_passes_and_waits_for_user(ctx: AppContext, models):
    a, b = make_tasks(ctx, "OIDC 仕様調査", "PKCE 導入検討")
    models["manager"].push(
        *plan_script(
            [a, b],
            [
                {"title": "OIDC 調査", "description": "OIDC の仕様を調べる"},
                {"title": "PKCE 調査", "description": "PKCE を調べる"},
                {"title": "統合レポート", "description": "両方をまとめる", "depends_on": [0, 1]},
            ],
        )
    )
    models["worker"].push(
        *worker_success("OIDC レポート"),
        *worker_success("PKCE レポート"),
        *worker_success("統合", with_artifact=False),
    )
    models["review"].push(*review_script({a: "passed", b: "passed"}))
    orch = orchestrator(ctx)
    await orch.run_cycle([Trigger("manual_run")])

    assert task_status(ctx, a) == "review_pending" and task_status(ctx, b) == "review_pending"
    with ctx.db.session() as s:
        exec_service = ExecutionService(s)
        plans, _ = exec_service.list_plans()
        assert len(plans) == 1 and plans[0].status == "passed"
        items = exec_service.ordered_work_items(plans[0].id)
        assert [i.status for i in items] == ["succeeded"] * 3
        # dependency order respected: worker runs happened in topological order
        runs = [
            r
            for r in s.execute(select(AgentRun).order_by(AgentRun.started_at)).scalars()
            if r.agent_type == "worker"
        ]
        assert [r.work_item_id for r in runs] == [i.id for i in items]
        assert all(r.status == "succeeded" and r.model == "fake:scripted" for r in runs)
        artifacts = ArtifactService(s, orch.store).list_for_plan(plans[0].id)
        assert len(artifacts) == 2 and all(x.status == "review_pending" for x in artifacts)
        assert artifacts[0].sources[0].reference == "https://example.com/spec"
        assert {x.id for x in ArtifactService(s, orch.store).list_for_task(b)} == {
            x.id for x in artifacts
        }  # shared plan artifacts visible from both tasks
        review = exec_service.latest_review(plans[0].id)
        assert review.status == "passed" and {r.task_id for r in review.task_results} == {a, b}
    assert any(n.title == "成果物の確認をお願いします" for n in notifications(ctx))
    assert orch.queue.pending_count() >= 1  # fresh manager execution queued
    assert orch.status.consecutive_no_progress == 0
    # fresh manager run re-evaluates all tasks with their new state
    models["manager"].push({"content": "確認待ちのため実行する作業はありません"})
    queued = orch.queue.drain()
    assert {t.type for t in queued} >= {"reevaluate", "review_completed", "work_item_completed"}
    await orch.run_cycle(queued)
    prompt = models["manager"].calls[-1][-1].content
    assert "review_pending" in prompt and a in prompt
    assert orch.status.consecutive_no_progress == 1
    # user approval completes the task and approves artifacts
    with ctx.db.session() as s:
        TaskService(s, ctx.broker).approve(a)
        assert TaskService(s).get(a).status == "completed"
        assert all(
            x.status == "approved" for x in ArtifactService(s, orch.store).list_for_task(a) if x.task_id == a
        )


@pytest.mark.asyncio
async def test_review_failure_triggers_replanning_for_failed_task_only(ctx: AppContext, models):
    a, b = make_tasks(ctx, "A", "B")
    models["manager"].push(*plan_script([a, b], [{"title": "調査", "description": "両方を調べる"}]))
    models["worker"].push(*worker_success("初回レポート"))
    models["review"].push(*review_script({a: "passed", b: "failed"}, feedback="B の比較表が不足"))
    # replanning script: only the failed task, parent filled automatically
    models["manager"].push(
        *plan_script(
            [b], [{"title": "比較表作成", "description": "B の比較表を追加する"}], objective="不足分の補完"
        )
    )
    models["worker"].push(*worker_success("比較表"))
    models["review"].push(*review_script({b: "passed"}))
    orch = orchestrator(ctx)
    await orch.run_cycle([Trigger("manual_run")])

    assert task_status(ctx, a) == "review_pending" and task_status(ctx, b) == "review_pending"
    with ctx.db.session() as s:
        exec_service = ExecutionService(s)
        plans, _ = exec_service.list_plans()
        by_attempt = {p.replanning_attempt: p for p in plans}
        assert by_attempt[0].status == "replanned" and by_attempt[1].status == "passed"
        assert by_attempt[1].parent_plan_id == by_attempt[0].id
        assert exec_service.plan_task_ids(by_attempt[1].id) == [b]
        from langchain_core.messages import HumanMessage

        prompts = [m.content for call in models["manager"].calls for m in call if isinstance(m, HumanMessage)]
        replan_prompt = next(p for p in prompts if "再計画モード" in p)
        assert "B の比較表が不足" in replan_prompt and "failed_plan" in replan_prompt
        manager_runs = [r for r in s.execute(select(AgentRun)).scalars() if r.agent_type == "manager"]
        assert any(r.trigger == "review_failed" for r in manager_runs)


@pytest.mark.asyncio
async def test_replanning_limit_stops_and_notifies(ctx: AppContext, models):
    (a,) = make_tasks(ctx, "難しいタスク")
    orch = orchestrator(ctx)
    models["manager"].push(*plan_script([a], [{"title": "試行", "description": "試す"}]))
    for _ in range(3):
        models["worker"].push(*worker_success("試行結果"))
        models["review"].push(*review_script({a: "failed"}, feedback="まだ不足"))
    models["manager"].push(*plan_script([a], [{"title": "再試行1", "description": "もう一度"}]))
    models["manager"].push(*plan_script([a], [{"title": "再試行2", "description": "さらに"}]))
    await orch.run_cycle([Trigger("manual_run")])

    assert task_status(ctx, a) == "blocked"
    with ctx.db.session() as s:
        plans, _ = ExecutionService(s).list_plans()
        assert sorted(p.replanning_attempt for p in plans) == [0, 1, 2]
        assert sorted(p.status for p in plans) == ["failed", "replanned", "replanned"]
        contexts = list(s.execute(select(TaskContext).where(TaskContext.task_id == a)).scalars())
        assert any(c.source == "retry_exhausted" for c in contexts)
    assert any(n.title == "AI の作業を停止しました" and n.level == "high" for n in notifications(ctx))
    assert models["manager"].remaining == 0  # no further replanning attempted


@pytest.mark.asyncio
async def test_replan_without_new_plan_stops_work(ctx: AppContext, models):
    (a,) = make_tasks(ctx, "T")
    models["manager"].push(*plan_script([a], [{"title": "w", "description": "w"}]))
    models["worker"].push(*worker_success())
    models["review"].push(*review_script({a: "failed"}))
    models["manager"].push({"content": "補える情報がないため再計画しません"})
    await orchestrator(ctx).run_cycle([Trigger("manual_run")])
    assert task_status(ctx, a) == "blocked"


@pytest.mark.asyncio
async def test_worker_retry_then_success(ctx: AppContext, models):
    (a,) = make_tasks(ctx, "再試行")
    models["manager"].push(*plan_script([a], [{"title": "w", "description": "w"}]))
    models["worker"].push(
        tool_call("report_work_result", status="failed", summary="一時的なエラー"), {"content": "失敗"}
    )
    models["worker"].push(*worker_success())
    models["review"].push(*review_script({a: "passed"}))
    await orchestrator(ctx).run_cycle([Trigger("manual_run")])
    with ctx.db.session() as s:
        plans, _ = ExecutionService(s).list_plans()
        item = ExecutionService(s).list_work_items(plans[0].id)[0]
        assert item.status == "succeeded" and item.retry_count == 1
        worker_runs = [r for r in s.execute(select(AgentRun)).scalars() if r.agent_type == "worker"]
        assert (
            len(worker_runs) == 2 and worker_runs[0].status == "failed" or worker_runs[1].status == "failed"
        )
    assert task_status(ctx, a) == "review_pending"


@pytest.mark.asyncio
async def test_worker_exception_exhausts_retries_and_fails_without_llm_review(ctx: AppContext, models):
    (a,) = make_tasks(ctx, "例外")
    models["manager"].push(*plan_script([a], [{"title": "w", "description": "w"}]))

    def boom(messages):
        raise RuntimeError("provider down")

    models["worker"].push(boom, boom)
    models["manager"].push({"content": "再計画しません"})
    orch = orchestrator(ctx)
    await orch.run_cycle([Trigger("manual_run")])
    with ctx.db.session() as s:
        plans, _ = ExecutionService(s).list_plans()
        item = ExecutionService(s).list_work_items(plans[0].id)[0]
        assert item.status == "failed" and item.retry_count == 1
        review = ExecutionService(s).latest_review(plans[0].id)
        assert review.status == "failed" and "作業が完了しなかった" in review.feedback
    assert models["review"].calls == []  # review skipped when nothing succeeded
    assert task_status(ctx, a) == "blocked"


@pytest.mark.asyncio
async def test_blocked_review_requests_user_input(ctx: AppContext, models):
    (a,) = make_tasks(ctx, "情報不足")
    models["manager"].push(*plan_script([a], [{"title": "w", "description": "w"}]))
    models["worker"].push(*worker_success())
    models["review"].push(*review_script({a: "blocked"}, feedback="対象システムの名称が必要です"))
    await orchestrator(ctx).run_cycle([Trigger("manual_run")])
    assert task_status(ctx, a) == "blocked"
    with ctx.db.session() as s:
        contexts = list(s.execute(select(TaskContext).where(TaskContext.task_id == a)).scalars())
        assert any(c.source == "review_blocked" and "対象システム" in c.context for c in contexts)
        plans, _ = ExecutionService(s).list_plans()
        assert plans[0].status == "blocked"
    assert any(n.title == "追加情報が必要です" for n in notifications(ctx))


@pytest.mark.asyncio
async def test_no_progress_limit_stops_reevaluation(ctx: AppContext, models):
    make_tasks(ctx, "何もしない")
    models["manager"].push(
        {"content": "何もしません"}, {"content": "まだ何もしません"}, {"content": "呼ばれないはず"}
    )
    orch = orchestrator(ctx)
    await orch.run_cycle([Trigger("reevaluate")])
    await orch.run_cycle([Trigger("reevaluate")])
    assert orch.status.consecutive_no_progress == 2
    await orch.run_cycle([Trigger("reevaluate")])
    assert len(models["manager"].calls) == 2  # third reevaluation skipped
    await orch.run_cycle([Trigger("task_created")])  # external trigger resets the counter
    assert len(models["manager"].calls) == 3
    assert orch.status.consecutive_no_progress == 1


@pytest.mark.asyncio
async def test_manager_tools_enforce_rules(ctx: AppContext):
    from app.agents.context import AgentContext
    from app.agents.tools.manager_tools import build_manager_tools

    (ai_task, user_task) = make_tasks(ctx, "AI用", "ユーザー用")
    with ctx.db.session() as s:
        from app.schemas.tasks import TaskUpdate

        TaskService(s).update(user_task, TaskUpdate(assignee="user"))
    agent_ctx = AgentContext(app=ctx, agent_type="manager", mode="evaluate")
    tools = {t.name: t for t in build_manager_tools(agent_ctx)}
    assert (
        tools["create_execution_plan"]
        .invoke({"objective": "o", "acceptance_criteria": "c", "task_ids": [user_task]})
        .startswith("error")
    )
    first = tools["create_execution_plan"].invoke(
        {"objective": "o", "acceptance_criteria": "c", "task_ids": [ai_task]}
    )
    assert "plan_id" in first
    assert "already has an active plan" in tools["create_execution_plan"].invoke(
        {"objective": "o2", "acceptance_criteria": "c", "task_ids": [ai_task]}
    )
    assert tools["update_task"].invoke({"task_id": ai_task, "status": "completed"}).startswith("error")
    assert (
        tools["record_decision"].invoke({"task_id": ai_task, "content": "x"}).startswith("error")
    )  # not in instruction mode
    assert "cycle" in tools["create_work_items"].invoke(
        {
            "plan_id": __import__("json").loads(first)["plan_id"],
            "items": [
                {"title": "a", "description": "a", "depends_on": [1]},
                {"title": "b", "description": "b", "depends_on": [0]},
            ],
        }
    )
    assert task_status(ctx, ai_task) == "in_progress"
    scheduled = tools["schedule_action"].invoke({"action_type": "manager_reevaluate", "delay_minutes": 30})
    assert "manager_reevaluate" in scheduled
    assert "疲れ" not in tools["get_user_state"].invoke({})


@pytest.mark.asyncio
async def test_one_shot_instruction_persists_changes(ctx: AppContext, models):
    (existing,) = make_tasks(ctx, "既存タスク")
    models["manager"].push(
        tool_call("create_task", title="週報を書く", description="金曜まで", assignee="ai"),
        tool_call("record_decision", task_id=existing, content="週報は Markdown で提出する"),
        tool_call("save_memory", content="ユーザーは金曜に週報を書く", scope="global", kind="ai_inference"),
        {"content": "タスクを作成し、決定事項を記録しました"},
    )
    orch = orchestrator(ctx)
    result = await orch.run_instruction(
        "週報タスクを作って。週報は Markdown で提出することに決めた。", [existing]
    )
    assert result.created_task_ids and result.decision_ids and "決定事項" in result.text
    with ctx.db.session() as s:
        created = TaskService(s).get(result.created_task_ids[0])
        assert created.title == "週報を書く" and TaskService(s).history(created.id)[0].changed_by == "ai"
        from app.services.chat_service import DecisionService

        assert DecisionService(s).active(existing)[0].content == "週報は Markdown で提出する"
        runs = [r for r in s.execute(select(AgentRun)).scalars()]
        assert runs[0].trigger == "user_instruction" and runs[0].status == "succeeded"
        from app.services.audit_service import AuditService

        rows, _ = AuditService(s).list(event_type="manager.instruction")
        assert rows and "週報" in rows[0].details
    assert "ワンショット指示モード" in models["manager"].calls[0][-1].content


@pytest.mark.asyncio
async def test_builtin_due_and_review_reminders(ctx: AppContext, models):
    from app.utils import iso_in

    with ctx.db.session() as s:
        soon = TaskService(s).create(TaskCreate(title="期限間近", due_at=iso_in(hours=2)))
        overdue = TaskService(s).create(TaskCreate(title="超過", due_at=iso_in(hours=-5)))
        TaskService(s).create(TaskCreate(title="余裕", due_at=iso_in(days=30)))
    models["manager"].push({"content": "nothing"})
    orch = orchestrator(ctx)
    await orch.run_cycle([Trigger("manual_run")])
    titles = {(n.title, n.task_id) for n in notifications(ctx)}
    assert ("期限が近づいています", soon.id) in titles and ("期限超過", overdue.id) in titles
    assert len([n for n in notifications(ctx) if n.title.startswith("期限")]) == 2
    models["manager"].push({"content": "nothing"})
    await orch.run_cycle([Trigger("manual_run")])  # same day -> deduplicated
    assert len([n for n in notifications(ctx) if n.title.startswith("期限")]) == 2
    with ctx.db.session() as s:
        from app.orchestrator.scheduler import SchedulerService

        assert SchedulerService(s).pending(action_type="manager_reevaluate")


@pytest.mark.asyncio
async def test_missing_api_key_skips_ai_and_notifies(ctx: AppContext):
    make_tasks(ctx, "x")
    ctx.llm_factory.provider_override = None  # real provider (openai) without a key
    orch = orchestrator(ctx)
    await orch.run_cycle([Trigger("manual_run")])
    assert orch.status.llm_issue and "API キー" in orch.status.llm_issue
    assert any(n.title == "API キーが未設定です" for n in notifications(ctx))
    assert orch.status_dict()["llm_ready"] is False


@pytest.mark.asyncio
async def test_pause_and_resume_persist(ctx: AppContext, models):
    orch = orchestrator(ctx)
    orch.pause()
    assert orch.paused and orch.status_dict()["state"] == "paused"
    other = Orchestrator(ctx)
    with ctx.db.session() as s:
        from app.services.settings_service import SettingsService

        assert SettingsService(s, ctx.settings).get_flag("manager_paused")
    other.resume()
    assert not other.paused and other.queue.pending_count() == 1


@pytest.mark.asyncio
async def test_chat_reply_uses_context_and_tools(ctx: AppContext, models):
    from app.agents.chat_agent import ChatAgent
    from app.services.chat_service import ChatService, DecisionService

    (a,) = make_tasks(ctx, "チャット対象")
    with ctx.db.session() as s:
        DecisionService(s).record(a, "Python 3.12 を使う")
        chat = ChatService(s).create_chat(a)
        ChatService(s).add_message(chat.id, "疲れているので軽めの作業にしたい。Python のバージョンは？")
        chat_id = chat.id
    models["manager"].push(
        tool_call("estimate_user_state", condition="疲れている"),
        {"content": "決定事項により Python 3.12 です。軽めの作業から進めましょう。"},
    )
    text = await ChatAgent(ctx).reply(chat_id)
    assert "3.12" in text
    with ctx.db.session() as s:
        messages, _ = ChatService(s).list_messages(chat_id)
        assert messages[-1].author_type == "ai" and messages[-1].content == text
        from app.services.user_state_service import UserStateService

        assert UserStateService(s).current_condition() == "疲れている"
    system_prompt = models["manager"].calls[0][0].content
    assert "Python 3.12 を使う" in system_prompt
