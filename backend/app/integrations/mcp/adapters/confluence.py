"""Confluence adapter (SPEC 17.11)."""

from __future__ import annotations

from typing import Any

from app.integrations.mcp.adapters.base import AdapterPreset, ServiceAdapter
from app.integrations.mcp.client import ToolInfo


class ConfluenceAdapter(ServiceAdapter):
    name = "confluence"
    label = "Confluence"
    description = "Search and read Confluence pages (e.g. via the mcp-atlassian server)."
    search_tool_candidates = ("confluence_search", "search_pages", "search")
    read_only_tools = (
        "confluence_search",
        "confluence_get_page",
        "confluence_get_page_children",
        "confluence_get_comments",
        "get_page",
        "search_pages",
    )
    external_write_tools = (
        "confluence_create_page",
        "confluence_update_page",
        "confluence_delete_page",
        "confluence_add_comment",
        "create_page",
        "update_page",
    )

    def preset(self) -> AdapterPreset:
        return AdapterPreset(
            adapter=self.name,
            label=self.label,
            description=self.description,
            transport="stdio",
            command="uvx",
            args=["mcp-atlassian"],
            auth_type="none",
            env_hints={
                "CONFLUENCE_URL": "https://your-site.atlassian.net/wiki",
                "CONFLUENCE_USERNAME": "you@example.com",
                "CONFLUENCE_API_TOKEN": "Atlassian API token",
            },
            tool_permissions=[
                {"tool_name": "confluence_create_page", "permission": "external_write", "enabled": False},
                {"tool_name": "confluence_update_page", "permission": "external_write", "enabled": False},
                {"tool_name": "confluence_delete_page", "permission": "external_write", "enabled": False},
            ],
        )

    def build_search_args(self, tool: ToolInfo, query: str, limit: int) -> dict[str, Any]:
        props = (tool.input_schema or {}).get("properties", {}) if isinstance(tool.input_schema, dict) else {}
        args: dict[str, Any] = {}
        if "query" in props:
            # mcp-atlassian accepts either plain text or CQL in ``query``
            args["query"] = query
        elif "cql" in props:
            escaped = query.replace('"', '\\"')
            args["cql"] = f'text ~ "{escaped}"'
        else:
            args = super().build_search_args(tool, query, limit)
        if "limit" in props:
            args["limit"] = limit
        return args

    def normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        data = super().normalize_item(item)
        data["space"] = (
            (item.get("space") or {}).get("key") if isinstance(item.get("space"), dict) else item.get("space")
        )
        data["source_type"] = "confluence"
        return data
