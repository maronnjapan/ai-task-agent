"""Task chat assistant (SPEC 13.1-13.2)."""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import BaseTool

from app.agents.base import AgentRunnerBase
from app.agents.context import AgentContext, clip
from app.agents.prompts.chat import CHAT_SYSTEM_PROMPT
from app.agents.tools.common import as_json, make_tool, memory_to_dict, task_to_dict
from app.agents.tools.worker_tools import _artifact_service
from app.schemas.memories import MemoryCreate
from app.services.chat_service import ChatService, DecisionService
from app.services.errors import ServiceError
from app.services.memory_service import MemoryService
from app.services.task_service import TaskService
from app.services.user_state_service import UserStateService
from app.utils import dumps

log = logging.getLogger(__name__)


def build_chat_tools(ctx: AgentContext, task_id: str) -> list[BaseTool]:
    def get_task() -> str:
        """Task details, decisions and open user contexts."""
        with ctx.session() as session:
            service = TaskService(session)
            task = service.get(task_id)
            return as_json(task_to_dict(task, {"decisions": [d.content for d in DecisionService(session).active(task.id)], "open_user_contexts": [c.context for c in service.open_contexts(task.id)]}))

    def search_memory(query: str, limit: int = 10) -> str:
        """Search long-term memory relevant to this task."""
        with ctx.session() as session:
            task = TaskService(session).get(task_id)
            rows = MemoryService(session).relevant_for_task(task, query=query, limit=limit)
            return as_json([memory_to_dict(m) for m in rows])

    def list_task_artifacts() -> str:
        """Artifacts linked to this task."""
        with ctx.session() as session:
            rows = _artifact_service(ctx, session).list_for_task(task_id)
            return as_json([{"id": a.id, "title": a.title, "version": a.version, "status": a.status} for a in rows])

    def read_artifact(artifact_id: str) -> str:
        """Read an artifact's current content."""
        with ctx.session() as session:
            service = _artifact_service(ctx, session)
            try:
                artifact = service.get(artifact_id)
                return as_json({"id": artifact.id, "title": artifact.title, "content": clip(service.read_content(artifact_id), 12_000)})
            except ServiceError as exc:
                return f"error: {exc.message}"

    def estimate_user_state(condition: str, expires_in_minutes: int = 240) -> str:
        """Record an estimate of the user's current condition (e.g. 疲れている, 忙しい). Expires automatically."""
        with ctx.session() as session:
            state = UserStateService(session).set(condition, source="chat_estimate", expires_in_minutes=expires_in_minutes, actor="ai")
            return as_json({"condition": state.condition, "source": state.source, "expires_at": state.expires_at})

    def save_memory(content: str, scope: str = "task", kind: str = "ai_inference") -> str:
        """Save a memory for this task (scope: task | category | global; kind: hypothesis | ai_inference | research)."""
        if kind == "decision":
            return "error: decisions must be recorded by the user through the UI"
        with ctx.session() as session:
            task = TaskService(session).get(task_id)
            try:
                memory = MemoryService(session).create(
                    MemoryCreate(scope=scope, task_id=task.id if scope == "task" else None, category_id=task.category_id if scope == "category" else None, content=content, source=f"chat:{ctx.recorder.get('chat_id')}", kind=kind),
                    actor="ai",
                )
            except (ServiceError, ValueError) as exc:
                return f"error: {exc}"
            return as_json({"id": memory.id})

    return [
        make_tool(get_task, "get_task", get_task.__doc__ or ""),
        make_tool(search_memory, "search_memory", search_memory.__doc__ or ""),
        make_tool(list_task_artifacts, "list_task_artifacts", list_task_artifacts.__doc__ or ""),
        make_tool(read_artifact, "read_artifact", read_artifact.__doc__ or ""),
        make_tool(estimate_user_state, "estimate_user_state", estimate_user_state.__doc__ or ""),
        make_tool(save_memory, "save_memory", save_memory.__doc__ or ""),
    ]


class ChatAgent(AgentRunnerBase):
    agent_type = "manager"  # chat uses the Manager model configuration
    max_iterations = 8

    async def reply(self, chat_id: str) -> str:
        """Generate and persist an AI reply for the latest user message of ``chat_id``."""
        with self.app.db.session() as session:
            chat_service = ChatService(session, self.app.broker)
            chat = chat_service.get_chat(chat_id)
            task = TaskService(session).get(chat.task_id)
            history_rows = chat_service.recent_messages(chat_id, limit=30)
            decisions = [d.content for d in DecisionService(session).active(task.id)]
            last_user = next((m.content for m in reversed(history_rows) if m.author_type == "user"), "")
            memories = [memory_to_dict(m) for m in MemoryService(session).relevant_for_task(task, query=last_user, limit=12)]
            state = UserStateService(session).current_condition()
            task_info = task_to_dict(task)
        history: list[BaseMessage] = []
        for row in history_rows[:-1] if history_rows and history_rows[-1].author_type == "user" else history_rows:
            if row.author_type == "user":
                history.append(HumanMessage(content=row.content))
            elif row.author_type == "ai":
                history.append(AIMessage(content=row.content))
        user_prompt = last_user or "(no message)"
        context_block = dumps({"task": task_info, "decisions": decisions, "memories": memories, "user_state": state, "chat_title": chat.title})
        system_prompt = CHAT_SYSTEM_PROMPT + "\n\n## タスクの文脈\n" + context_block
        ctx = AgentContext(app=self.app, agent_type="manager", mode="chat")
        ctx.recorder["chat_id"] = chat_id
        tools = build_chat_tools(ctx, task.id)
        outcome = await self.invoke(system_prompt, user_prompt, tools, history=history)
        text = outcome.text or "（応答を生成できませんでした）"
        with self.app.db.session() as session:
            ChatService(session, self.app.broker).add_message(chat_id, text, author_type="ai")
        return text
