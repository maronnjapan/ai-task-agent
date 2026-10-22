"""Slack adapter (SPEC 17.10): read conversations, never post without approval."""

from __future__ import annotations

from typing import Any

from app.integrations.mcp.adapters.base import AdapterPreset, ServiceAdapter
from app.integrations.mcp.client import ToolInfo


class SlackAdapter(ServiceAdapter):
    name = "slack"
    label = "Slack"
    description = "Search Slack messages, threads and channels through a Slack MCP server."
    search_tool_candidates = ("search_messages", "conversations_search_messages", "slack_search", "search")
    read_only_tools = (
        "list_channels",
        "get_channel_history",
        "get_thread_replies",
        "get_users",
        "get_user_profile",
        "search_messages",
        "conversations_history",
        "conversations_replies",
        "channels_list",
        "users_list",
    )
    external_write_tools = (
        "post_message",
        "reply_to_thread",
        "add_reaction",
        "conversations_add_message",
        "chat_postmessage",
        "send_message",
    )
    tool_name_aliases = {"search": "slack_search_messages"}

    def preset(self) -> AdapterPreset:
        return AdapterPreset(
            adapter=self.name,
            label=self.label,
            description=self.description,
            transport="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-slack"],
            auth_type="none",
            env_hints={"SLACK_BOT_TOKEN": "xoxb-... (Bot User OAuth Token)", "SLACK_TEAM_ID": "T0123456"},
            tool_permissions=[
                {"tool_name": "slack_post_message", "permission": "external_write", "enabled": False},
                {"tool_name": "slack_reply_to_thread", "permission": "external_write", "enabled": False},
                {"tool_name": "slack_add_reaction", "permission": "external_write", "enabled": False},
            ],
        )

    def build_search_args(self, tool: ToolInfo, query: str, limit: int) -> dict[str, Any]:
        args = super().build_search_args(tool, query, limit)
        props = (tool.input_schema or {}).get("properties", {}) if isinstance(tool.input_schema, dict) else {}
        if "count" in props:
            args["count"] = limit
        return args

    def normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        data = super().normalize_item(item)
        channel = item.get("channel")
        if isinstance(channel, dict):
            channel = channel.get("name") or channel.get("id")
        data["channel"] = channel
        data["user"] = item.get("username") or item.get("user")
        data["source_type"] = "slack"
        return data
