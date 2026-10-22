"""Scripted chat model used by the automated tests and the ``fake`` provider.

The model replays a list of responses. Each response is either an
``AIMessage`` or a dict ``{"content": str, "tool_calls": [{"name", "args"}]}``.
When the script runs out it returns a plain "done" message so graphs terminate.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field, PrivateAttr

from app.utils import new_id

ScriptItem = AIMessage | dict[str, Any] | Callable[[list[BaseMessage]], AIMessage | dict[str, Any]]


def make_ai_message(item: AIMessage | dict[str, Any]) -> AIMessage:
    if isinstance(item, AIMessage):
        return item
    tool_calls = []
    for call in item.get("tool_calls") or []:
        tool_calls.append(
            {
                "name": call["name"],
                "args": call.get("args") or {},
                "id": call.get("id") or f"call_{new_id()[:8]}",
                "type": "tool_call",
            }
        )
    return AIMessage(content=item.get("content") or "", tool_calls=tool_calls)


class ScriptedChatModel(BaseChatModel):
    """Deterministic chat model for tests. Thread-safe; scripts are consumed in order."""

    script: list[Any] = Field(default_factory=list)
    model_name: str = "scripted"
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tools: list[str] = Field(default_factory=list)

    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedChatModel:  # type: ignore[override]
        names = []
        for tool in tools:
            name = (
                getattr(tool, "name", None)
                or (tool.get("name") if isinstance(tool, dict) else None)
                or getattr(tool, "__name__", "tool")
            )
            names.append(str(name))
        self.bound_tools = names
        return self

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        with self._lock:
            self.calls.append(list(messages))
            if not self.script:
                return AIMessage(content="done")
            item = self.script.pop(0)
        if callable(item) and not isinstance(item, AIMessage | dict):
            item = item(messages)
        return make_ai_message(item)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        message = self._next(messages)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def push(self, *items: Any) -> None:
        with self._lock:
            self.script.extend(items)

    @property
    def remaining(self) -> int:
        return len(self.script)
