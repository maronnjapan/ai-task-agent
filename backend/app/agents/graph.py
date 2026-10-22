"""Generic tool-calling agent graph built with LangGraph (SPEC 8.1)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Annotated, Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

log = logging.getLogger(__name__)


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    iterations: int


def build_agent_graph(model: BaseChatModel, tools: Sequence[BaseTool], max_iterations: int = 12):
    """Compile a graph: agent -> (tools -> agent)* -> END.

    Each LangGraph execution is an independent run; the caller builds all
    necessary context into the initial messages.
    """
    bound = model.bind_tools(list(tools)) if tools else model
    tool_node = ToolNode(list(tools), handle_tool_errors=True) if tools else None

    async def call_model(state: AgentState) -> dict[str, Any]:
        response = await bound.ainvoke(state["messages"])
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(getattr(response, "content", response)))
        return {"messages": [response], "iterations": state.get("iterations", 0) + 1}

    def route(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls and tool_node is not None:
            if state.get("iterations", 0) >= max_iterations:
                return "limit"
            return "tools"
        return "end"

    async def limit_reached(state: AgentState) -> dict[str, Any]:
        last = state["messages"][-1]
        notes = []
        if isinstance(last, AIMessage):
            for call in last.tool_calls:
                notes.append(
                    ToolMessage(
                        content="Iteration limit reached; the tool call was not executed. Finish now.",
                        tool_call_id=call["id"],
                    )
                )
        return {"messages": notes}

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("limit", limit_reached)
    if tool_node is not None:
        graph.add_node("tools", tool_node)
        graph.add_edge("tools", "agent")
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        route,
        {"tools": "tools", "limit": "limit", "end": END} if tool_node else {"end": END, "limit": "limit"},
    )
    graph.add_edge("limit", END)
    return graph.compile()


def initial_messages(
    system_prompt: str, user_prompt: str, history: Sequence[BaseMessage] | None = None
) -> list[BaseMessage]:
    messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
    if history:
        messages.extend(history)
    messages.append(HumanMessage(content=user_prompt))
    return messages


def final_text(messages: Sequence[BaseMessage]) -> str:
    for message in reversed(list(messages)):
        if isinstance(message, AIMessage):
            content = message.content
            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(str(part.get("text", "")))
                    elif isinstance(part, str):
                        parts.append(part)
                content = "\n".join(parts)
            if content:
                return str(content).strip()
    return ""


def tool_calls_made(messages: Sequence[BaseMessage]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                calls.append({"name": call["name"], "args": call.get("args", {})})
    return calls
