"""Google Drive adapter (SPEC 17.11): document search and retrieval."""

from __future__ import annotations

from typing import Any

from app.integrations.mcp.adapters.base import AdapterPreset, ServiceAdapter
from app.integrations.mcp.client import ToolInfo


class GoogleDriveAdapter(ServiceAdapter):
    name = "google_drive"
    label = "Google Drive"
    description = "Search and read Google Drive documents through a Google Drive MCP server."
    search_tool_candidates = ("gdrive_search", "search_files", "drive_search", "search")
    read_only_tools = (
        "gdrive_search",
        "gdrive_read_file",
        "read_file",
        "get_file",
        "list_files",
        "search_files",
    )
    external_write_tools = ("create_file", "update_file", "delete_file", "share_file", "upload")

    def preset(self) -> AdapterPreset:
        return AdapterPreset(
            adapter=self.name,
            label=self.label,
            description=self.description,
            transport="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-gdrive"],
            auth_type="none",
            env_hints={
                "GDRIVE_CREDENTIALS_PATH": "path to the OAuth credentials json created by the server's auth step"
            },
        )

    def build_search_args(self, tool: ToolInfo, query: str, limit: int) -> dict[str, Any]:
        args = super().build_search_args(tool, query, limit)
        props = (tool.input_schema or {}).get("properties", {}) if isinstance(tool.input_schema, dict) else {}
        if "pageSize" in props:
            args["pageSize"] = limit
        return args

    def normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        data = super().normalize_item(item)
        data["mime_type"] = item.get("mimeType") or item.get("mime_type")
        data["source_type"] = "google_drive"
        return data
