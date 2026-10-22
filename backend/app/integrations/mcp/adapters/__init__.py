"""Service-specific MCP adapters (SPEC 17.7 - 17.11)."""

from __future__ import annotations

from app.integrations.mcp.adapters.base import ServiceAdapter
from app.integrations.mcp.adapters.confluence import ConfluenceAdapter
from app.integrations.mcp.adapters.generic import GenericAdapter
from app.integrations.mcp.adapters.google_drive import GoogleDriveAdapter
from app.integrations.mcp.adapters.jira import JiraAdapter
from app.integrations.mcp.adapters.slack import SlackAdapter

_ADAPTERS: dict[str, ServiceAdapter] = {
    adapter.name: adapter for adapter in (GenericAdapter(), SlackAdapter(), GoogleDriveAdapter(), ConfluenceAdapter(), JiraAdapter())
}


def get_adapter(name: str | None) -> ServiceAdapter:
    return _ADAPTERS.get((name or "generic").lower(), _ADAPTERS["generic"])


def register_adapter(adapter: ServiceAdapter) -> None:
    _ADAPTERS[adapter.name] = adapter


def list_adapters() -> list[ServiceAdapter]:
    return list(_ADAPTERS.values())


__all__ = ["ServiceAdapter", "get_adapter", "register_adapter", "list_adapters"]
