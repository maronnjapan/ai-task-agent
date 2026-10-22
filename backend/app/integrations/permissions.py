"""MCP tool permission classes (SPEC 17.14)."""

from __future__ import annotations

import re

from app.models.enums import ToolPermission

_EXTERNAL_WRITE = re.compile(
    r"(post|send|publish|reply|create|update|delete|remove|write|upload|edit|move|transition|comment|share|invite|add_|set_|assign|archive|notify|mail|email|put_)",
    re.IGNORECASE,
)
_READ = re.compile(
    r"(search|get|list|read|fetch|find|query|lookup|describe|download|view|show|history|count)", re.IGNORECASE
)


def classify_tool(tool_name: str, description: str | None = None) -> str:
    """Heuristic default classification; explicit settings in ``mcp_tool_permissions`` override it."""
    name = tool_name.lower()
    if _READ.search(name) and not _EXTERNAL_WRITE.search(name):
        return ToolPermission.READ
    if _EXTERNAL_WRITE.search(name):
        return ToolPermission.EXTERNAL_WRITE
    if description and _EXTERNAL_WRITE.search(description) and not _READ.search(name):
        return ToolPermission.EXTERNAL_WRITE
    if description and _READ.search(description):
        return ToolPermission.READ
    # Unknown tools fail closed: they need user approval until the user classifies them (SPEC 17.14).
    return ToolPermission.EXTERNAL_WRITE


def requires_approval(permission: str) -> bool:
    return permission == ToolPermission.EXTERNAL_WRITE


def validate_permission(value: str) -> str:
    return str(ToolPermission(value))
