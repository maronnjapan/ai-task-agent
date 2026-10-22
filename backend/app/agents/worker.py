"""Worker AI (SPEC 7.2)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import AgentRunnerBase
from app.agents.context import AgentContext
from app.agents.prompts.worker import WORKER_SYSTEM_PROMPT
from app.agents.tools.worker_tools import build_execution_context, build_worker_tools, result_from_recorder
from app.utils import dumps

log = logging.getLogger(__name__)


@dataclass
class WorkerResult:
    status: str
    summary: str
    artifact_ids: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self, work_item_id: str) -> dict[str, Any]:
        return {
            "work_item_id": work_item_id,
            "status": self.status,
            "summary": self.summary,
            "artifact_ids": self.artifact_ids,
            "sources": self.sources,
            "blockers": self.blockers,
        }


class WorkerAgent(AgentRunnerBase):
    agent_type = "worker"
    max_iterations = 24

    def system_prompt(self) -> str:
        config = self.llm_config()
        prompt = WORKER_SYSTEM_PROMPT
        if config.custom_prompt:
            prompt += "\n\n## 追加のシステム指示\n" + config.custom_prompt
        return prompt

    async def run(self, plan_id: str, work_item_id: str, run_id: str | None = None) -> WorkerResult:
        ctx = AgentContext(
            app=self.app,
            agent_type="worker",
            run_id=run_id,
            plan_id=plan_id,
            work_item_id=work_item_id,
            mode="run",
        )
        with self.app.db.session() as session:
            context = build_execution_context(ctx, session)
            ctx.task_ids = [t["id"] for t in context.get("tasks", [])]
        mcp_tools = []
        if self.app.mcp_registry is not None:
            try:
                mcp_tools = await self.app.mcp_registry.langchain_tools(ctx)
            except Exception:  # noqa: BLE001
                log.exception("failed to load MCP tools")
        tools = build_worker_tools(ctx, mcp_tools=mcp_tools)
        prompt = (
            "## 作業コンテキスト\n"
            + dumps(context)
            + "\n\n上記の Work Item を実行し、最後に report_work_result を呼んでください。"
        )
        outcome = await self.invoke(self.system_prompt(), prompt, tools)
        result = result_from_recorder(ctx, outcome.text)
        return WorkerResult(
            status=result["status"],
            summary=result.get("summary", ""),
            artifact_ids=list(result.get("artifact_ids") or []),
            sources=list(result.get("sources") or []),
            blockers=list(result.get("blockers") or []),
            text=outcome.text,
            tool_calls=outcome.tool_calls,
        )
