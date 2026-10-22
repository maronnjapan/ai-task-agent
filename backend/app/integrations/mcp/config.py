"""Connection configuration model shared by the registry, client and API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models import MCPConnection
from app.utils import loads


@dataclass
class ConnectionConfig:
    id: str
    name: str
    adapter: str = "generic"
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    auth_type: str = "none"
    auth_config: dict[str, Any] = field(default_factory=dict)
    secret_ref: str | None = None
    timeout_seconds: int = 30
    enabled: bool = True
    allowed_tools: list[str] = field(default_factory=list)
    tool_permissions: dict[str, tuple[str, bool]] = field(
        default_factory=dict
    )  # name -> (permission, enabled)

    @classmethod
    def from_model(cls, row: MCPConnection) -> ConnectionConfig:
        return cls(
            id=row.id,
            name=row.name,
            adapter=row.adapter,
            transport=row.transport,
            command=row.command,
            args=list(loads(row.args, []) or []),
            env=dict(loads(row.env, {}) or {}),
            url=row.url,
            headers=dict(loads(row.headers, {}) or {}),
            auth_type=row.auth_type,
            auth_config=dict(loads(row.auth_config, {}) or {}),
            secret_ref=row.secret_ref,
            timeout_seconds=row.timeout_seconds,
            enabled=row.enabled,
            allowed_tools=list(loads(row.allowed_tools, []) or []),
            tool_permissions={p.tool_name: (p.permission, p.enabled) for p in row.tool_permissions},
        )

    def secret_name(self) -> str:
        return self.secret_ref or f"MCP_{self.id.replace('-', '_').upper()}_SECRET"

    def oauth_secret_name(self) -> str:
        return f"MCP_{self.id.replace('-', '_').upper()}_OAUTH"
