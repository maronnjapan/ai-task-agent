"""Worker AI tools (SPEC 26.2)."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool

from app.agents.context import AgentContext, clip, wrap_external
from app.agents.tools.common import as_json, make_tool, memory_to_dict, task_to_dict
from app.integrations.local_files import LocalFileAccessError, LocalFileSource
from app.services.artifact_service import ArtifactService
from app.services.chat_service import DecisionService
from app.services.errors import ServiceError
from app.services.execution_service import ExecutionService
from app.services.memory_service import MemoryService
from app.services.settings_service import SettingsService
from app.services.task_service import TaskService
from app.utils import loads


def _artifact_service(ctx: AgentContext, session) -> ArtifactService:
    from app.infrastructure.artifact_store import ArtifactStore

    store = ctx.app.extras.get("artifact_store") or ArtifactStore(ctx.app.paths.artifacts)
    return ArtifactService(session, store, ctx.app.broker)


def build_execution_context(ctx: AgentContext, session) -> dict[str, Any]:
    """Everything a Worker needs (SPEC 8.5): instructions, objective, criteria, memories, dependency results."""
    exec_service = ExecutionService(session)
    plan = exec_service.get_plan(ctx.plan_id) if ctx.plan_id else None
    item = exec_service.get_work_item(ctx.work_item_id) if ctx.work_item_id else None
    task_service = TaskService(session)
    memory_service = MemoryService(session)
    tasks_data = []
    memories: dict[str, dict] = {}
    for link in plan.task_links if plan else []:
        try:
            task = task_service.get(link.task_id)
        except ServiceError:
            continue
        decisions = [d.content for d in DecisionService(session).active(task.id)]
        contexts = [{"context": c.context, "source": c.source} for c in task_service.open_contexts(task.id)]
        tasks_data.append(task_to_dict(task, {"acceptance_criteria": link.acceptance_criteria, "decisions": decisions, "open_user_contexts": contexts}))
        for memory in memory_service.relevant_for_task(task, query=item.description if item else None, limit=10):
            memories[memory.id] = memory_to_dict(memory)
    deps_results = []
    if plan and item:
        deps = exec_service.dependencies(plan.id)
        for dep_id in sorted(deps.get(item.id, ())):
            dep = exec_service.get_work_item(dep_id)
            deps_results.append({"work_item_id": dep.id, "title": dep.title, "status": dep.status, "result": loads(dep.result, None)})
    artifacts = []
    if plan:
        for artifact in _artifact_service(ctx, session).list_for_plan(plan.id):
            artifacts.append({"id": artifact.id, "title": artifact.title, "version": artifact.version, "status": artifact.status, "task_id": artifact.task_id})
    return {
        "work_item": {"id": item.id, "title": item.title, "description": item.description, "retry_count": item.retry_count} if item else None,
        "plan": {"id": plan.id, "objective": plan.objective, "acceptance_criteria": plan.acceptance_criteria, "replanning_attempt": plan.replanning_attempt} if plan else None,
        "tasks": tasks_data,
        "memories": list(memories.values()),
        "dependency_results": deps_results,
        "existing_artifacts": artifacts,
        "previous_review": _previous_review(exec_service, plan) if plan else None,
    }


def _previous_review(exec_service: ExecutionService, plan) -> dict | None:
    if not plan.parent_plan_id:
        return None
    review = exec_service.latest_review(plan.parent_plan_id)
    if review is None:
        return None
    return {"status": review.status, "feedback": review.feedback, "task_results": [{"task_id": r.task_id, "status": r.status, "feedback": r.feedback} for r in review.task_results]}


def build_worker_tools(ctx: AgentContext, mcp_tools: list[BaseTool] | None = None) -> list[BaseTool]:
    app = ctx.app

    def get_work_item() -> str:
        """The work item assigned to this run (instructions, status, retry count)."""
        with ctx.session() as session:
            item = ExecutionService(session).get_work_item(ctx.work_item_id)
            return as_json({"id": item.id, "title": item.title, "description": item.description, "status": item.status, "retry_count": item.retry_count, "plan_id": item.execution_plan_id})

    def get_execution_context() -> str:
        """Plan objective, acceptance criteria, related tasks, decisions, memories, dependency results and existing artifacts."""
        with ctx.session() as session:
            return as_json(build_execution_context(ctx, session))

    def _local_source(session) -> LocalFileSource:
        return LocalFileSource(SettingsService(session, app.settings).get_local_sources())

    def search_local_files(query: str, limit: int = 20) -> str:
        """Search the user's configured local directories for files/lines containing all query terms."""
        with ctx.session() as session:
            source = _local_source(session)
        if not source.roots:
            return "no local directories are configured in settings"
        hits = source.search(query, limit=limit)
        return wrap_external(as_json([h.__dict__ for h in hits])) if hits else "no matches"

    def read_local_file(path: str) -> str:
        """Read a local file (must be inside the configured directories and an allowed extension)."""
        with ctx.session() as session:
            source = _local_source(session)
        try:
            return wrap_external(source.read(path))
        except (LocalFileAccessError, FileNotFoundError) as exc:
            return f"error: {exc}"

    def _service_search(service: str):
        async def _search(query: str, limit: int = 10) -> str:
            registry = app.mcp_registry
            if registry is None:
                return f"error: {service} is not configured"
            try:
                results = await registry.search_service(service, query, limit=limit, agent_ctx=ctx)
            except Exception as exc:  # noqa: BLE001 - reported to the model
                return f"error: {service} search failed: {exc}"
            if not results:
                return f"no results from {service}"
            return wrap_external(as_json(results))

        return _search

    def search_memory(query: str, task_id: str | None = None, limit: int = 10) -> str:
        """Search long-term memory (global, category and task scopes)."""
        with ctx.session() as session:
            service = MemoryService(session)
            if task_id:
                try:
                    task = TaskService(session).get(task_id)
                except ServiceError as exc:
                    return f"error: {exc.message}"
                rows = service.relevant_for_task(task, query=query, limit=limit)
            else:
                rows = service.search(query, limit=limit)
            return as_json([memory_to_dict(m) for m in rows])

    def read_artifact(artifact_id: str, version: int | None = None) -> str:
        """Read a Markdown artifact (optionally a specific version)."""
        with ctx.session() as session:
            service = _artifact_service(ctx, session)
            try:
                artifact = service.get(artifact_id)
                content = service.read_content(artifact_id, version)
            except ServiceError as exc:
                return f"error: {exc.message}"
            return as_json({"id": artifact.id, "title": artifact.title, "version": version or artifact.version, "status": artifact.status, "content": clip(content)})

    def create_markdown_artifact(title: str, content: str, task_id: str | None = None, sources: list[dict[str, Any]] | None = None) -> str:
        """Create a Markdown artifact for a task of this plan. sources: [{"title": str, "reference": url-or-path, "source_type": web|file|slack|...}]."""
        with ctx.session() as session:
            exec_service = ExecutionService(session)
            plan_tasks = exec_service.plan_task_ids(ctx.plan_id) if ctx.plan_id else []
            primary = task_id or (plan_tasks[0] if plan_tasks else None)
            if plan_tasks and primary not in plan_tasks:
                return f"error: task {primary} is not part of this plan"
            try:
                artifact = _artifact_service(ctx, session).create(
                    title=title,
                    content=content,
                    task_id=primary,
                    work_item_id=ctx.work_item_id,
                    execution_plan_id=ctx.plan_id,
                    related_task_ids=plan_tasks,
                    sources=sources or [],
                    actor="ai",
                )
            except ServiceError as exc:
                return f"error: {exc.message}"
            ctx.record("artifacts", artifact.id)
            return as_json({"artifact_id": artifact.id, "version": artifact.version, "file_path": artifact.file_path})

    def update_markdown_artifact(artifact_id: str, content: str, change_note: str | None = None, sources: list[dict[str, Any]] | None = None) -> str:
        """Revise an existing artifact (creates a new version)."""
        with ctx.session() as session:
            try:
                artifact = _artifact_service(ctx, session).update_content(artifact_id, content, change_note=change_note, actor="ai", sources=sources)
            except ServiceError as exc:
                return f"error: {exc.message}"
            ctx.record("artifacts", artifact.id)
            return as_json({"artifact_id": artifact.id, "version": artifact.version})

    def report_work_result(status: str, summary: str, artifact_ids: list[str] | None = None, sources: list[dict[str, Any]] | None = None, blockers: list[str] | None = None) -> str:
        """Report the final result of this work item (status: succeeded | failed | blocked). Call exactly once at the end."""
        if status not in ("succeeded", "failed", "blocked"):
            return "error: status must be succeeded, failed or blocked"
        result = {
            "work_item_id": ctx.work_item_id,
            "status": status,
            "summary": summary,
            "artifact_ids": list(dict.fromkeys((artifact_ids or []) + ctx.recorded("artifacts"))),
            "sources": sources or [],
            "blockers": blockers or [],
        }
        ctx.recorder["work_result"] = result
        return "recorded"

    tools: list[BaseTool] = [
        make_tool(get_work_item, "get_work_item", get_work_item.__doc__ or ""),
        make_tool(get_execution_context, "get_execution_context", get_execution_context.__doc__ or ""),
        make_tool(search_local_files, "search_local_files", search_local_files.__doc__ or ""),
        make_tool(read_local_file, "read_local_file", read_local_file.__doc__ or ""),
        make_tool(search_memory, "search_memory", search_memory.__doc__ or ""),
        make_tool(read_artifact, "read_artifact", read_artifact.__doc__ or ""),
        make_tool(create_markdown_artifact, "create_markdown_artifact", create_markdown_artifact.__doc__ or ""),
        make_tool(update_markdown_artifact, "update_markdown_artifact", update_markdown_artifact.__doc__ or ""),
        make_tool(report_work_result, "report_work_result", report_work_result.__doc__ or ""),
    ]
    for service, label in (("slack", "Slack messages and threads"), ("google_drive", "Google Drive documents"), ("confluence", "Confluence pages"), ("jira", "Jira issues")):
        coroutine = _service_search(service)

        def _sync(query: str, limit: int = 10, _coro=coroutine) -> str:
            import asyncio

            return asyncio.run(_coro(query, limit))

        tools.append(make_tool(_sync, f"search_{service}", f"Search {label} through the configured MCP connection (read-only).", coroutine=coroutine))
    tools.extend(mcp_tools or [])
    return tools


def result_from_recorder(ctx: AgentContext, final_text: str) -> dict[str, Any]:
    """Fallback result when the worker did not call report_work_result."""
    recorded = ctx.recorder.get("work_result")
    if recorded:
        return recorded
    artifacts = ctx.recorded("artifacts")
    status = "succeeded" if artifacts else "failed"
    return {
        "work_item_id": ctx.work_item_id,
        "status": status,
        "summary": final_text or ("Worker finished without an explicit report" if artifacts else "Worker did not report a result"),
        "artifact_ids": list(dict.fromkeys(artifacts)),
        "sources": [],
        "blockers": [] if artifacts else ["no_report"],
    }


def _json_or_text(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value
