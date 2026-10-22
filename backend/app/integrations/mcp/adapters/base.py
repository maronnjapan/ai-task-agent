from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.infrastructure.secrets.base import SecretProvider
from app.integrations.mcp.client import ToolInfo, ToolResult
from app.integrations.mcp.config import ConnectionConfig
from app.integrations.permissions import classify_tool


@dataclass
class AdapterPreset:
    adapter: str
    label: str
    description: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    auth_type: str = "none"
    auth_config: dict[str, Any] = field(default_factory=dict)
    env_hints: dict[str, str] = field(default_factory=dict)
    tool_permissions: list[dict[str, Any]] = field(default_factory=list)


class ServiceAdapter:
    """Base adapter: tool name mapping, argument/response normalisation, permission defaults."""

    name = "generic"
    label = "Generic MCP server"
    description = "Any MCP server reachable over stdio or Streamable HTTP."
    search_tool_candidates: tuple[str, ...] = ("search",)
    read_only_tools: tuple[str, ...] = ()
    external_write_tools: tuple[str, ...] = ()
    tool_name_aliases: dict[str, str] = {}

    # --- configuration -----------------------------------------------
    def preset(self) -> AdapterPreset:
        return AdapterPreset(adapter=self.name, label=self.label, description=self.description)

    def custom_auth(self, config: ConnectionConfig, secret_store: SecretProvider):
        return None

    # --- tool mapping --------------------------------------------------
    def map_tool_name(self, name: str) -> str:
        return self.tool_name_aliases.get(name, name)

    def transform_args(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return arguments

    def classify(self, tool: ToolInfo) -> str:
        lowered = tool.name.lower()
        if any(lowered == t or lowered.endswith(t) for t in self.external_write_tools):
            return "external_write"
        if any(lowered == t or lowered.endswith(t) for t in self.read_only_tools):
            return "read"
        return classify_tool(tool.name, tool.description)

    # --- search helpers ------------------------------------------------
    def pick_search_tool(self, tools: list[ToolInfo]) -> ToolInfo | None:
        names = {t.name.lower(): t for t in tools}
        for candidate in self.search_tool_candidates:
            for lowered, tool in names.items():
                if lowered == candidate or lowered.endswith(candidate) or candidate in lowered:
                    return tool
        return None

    def build_search_args(self, tool: ToolInfo, query: str, limit: int) -> dict[str, Any]:
        props = (tool.input_schema or {}).get("properties", {}) if isinstance(tool.input_schema, dict) else {}
        args: dict[str, Any] = {}
        for key in ("query", "q", "search", "text", "keyword", "jql", "cql"):
            if key in props:
                args[key] = query
                break
        if not args and props:
            first = next(iter(props))
            args[first] = query
        for key in ("limit", "max_results", "maxResults", "count", "page_size", "pageSize"):
            if key in props:
                args[key] = limit
                break
        return args

    def normalize_results(self, tool_name: str, result: ToolResult) -> list[dict[str, Any]]:
        """Best-effort normalisation into ``[{title, snippet, url, id, ...}]``."""
        payload: Any = result.structured
        if payload is None:
            try:
                payload = json.loads(result.text)
            except (TypeError, ValueError):
                payload = None
        items: list[Any]
        if isinstance(payload, dict):
            for key in ("results", "items", "messages", "files", "issues", "pages", "matches", "data"):
                if isinstance(payload.get(key), list):
                    items = payload[key]
                    break
            else:
                items = [payload]
        elif isinstance(payload, list):
            items = payload
        else:
            return [{"title": tool_name, "snippet": result.text[:2000], "url": None}] if result.text else []
        normalised = []
        for item in items:
            if isinstance(item, dict):
                normalised.append(self.normalize_item(item))
            else:
                normalised.append({"title": tool_name, "snippet": str(item)[:1000], "url": None})
        return normalised

    def normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": _first(item, ("title", "name", "summary", "subject", "key")),
            "snippet": _clip(_first(item, ("snippet", "text", "content", "body", "description", "excerpt"))),
            "url": _first(item, ("url", "permalink", "link", "href", "webViewLink", "self")),
            "id": _first(item, ("id", "key", "ts")),
            "updated_at": _first(item, ("updated", "updated_at", "modifiedTime", "ts", "created")),
        }

    def translate_error(self, exc: Exception) -> str:
        return f"{self.label}: {exc}"

    def rate_limit_delay(self, exc: Exception) -> float | None:
        match = re.search(r"retry[- ]after[:= ]+(\d+)", str(exc), re.IGNORECASE)
        return float(match.group(1)) if match else None


def _first(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            value = item[key]
            if isinstance(value, dict):
                return (
                    _first(value, ("text", "name", "title", "value"))
                    or json.dumps(value, ensure_ascii=False)[:200]
                )
            return value
    return None


def _clip(value: Any, limit: int = 1000) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "..."
    return value
