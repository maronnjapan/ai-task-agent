"""Shared runner for the three agents."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool

from app.agents.graph import build_agent_graph, final_text, initial_messages, tool_calls_made
from app.context import AppContext
from app.llm.configuration import LLMConfig
from app.services.settings_service import SettingsService

log = logging.getLogger(__name__)


@dataclass
class AgentOutcome:
    text: str
    messages: list[BaseMessage] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    iterations: int = 0


class AgentRunnerBase:
    agent_type = "manager"
    max_iterations = 12

    def __init__(self, app: AppContext):
        self.app = app

    def llm_config(self) -> LLMConfig:
        with self.app.db.session() as session:
            llm = SettingsService(session, self.app.settings).get_llm()
        agent_settings = getattr(llm, self.agent_type)
        return LLMConfig.from_settings(self.agent_type, agent_settings)

    def model(self, config: LLMConfig | None = None):
        assert self.app.llm_factory is not None, "LLM factory not initialised"
        return self.app.llm_factory.create(config or self.llm_config())

    async def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: Sequence[BaseTool],
        history: Sequence[BaseMessage] | None = None,
        config: LLMConfig | None = None,
        max_iterations: int | None = None,
    ) -> AgentOutcome:
        model = self.model(config)
        graph = build_agent_graph(model, tools, max_iterations or self.max_iterations)
        state = {"messages": initial_messages(system_prompt, user_prompt, history), "iterations": 0}
        result = await graph.ainvoke(state, config={"recursion_limit": (max_iterations or self.max_iterations) * 2 + 10})
        messages = list(result["messages"])
        return AgentOutcome(
            text=final_text(messages),
            messages=messages,
            tool_calls=tool_calls_made(messages),
            iterations=int(result.get("iterations", 0)),
        )
