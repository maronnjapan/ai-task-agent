from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ToolPermissionIn(BaseModel):
    tool_name: str
    permission: str = "read"
    enabled: bool = True


class IntegrationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    adapter: str = "generic"
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    auth_type: str = "none"
    auth_config: dict[str, Any] = Field(default_factory=dict)
    secret: str | None = None  # API token / bearer token (stored via Secret Provider, never returned)
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    enabled: bool = True
    allowed_tools: list[str] = Field(default_factory=list)
    tool_permissions: list[ToolPermissionIn] = Field(default_factory=list)


class IntegrationUpdate(BaseModel):
    name: str | None = None
    adapter: str | None = None
    transport: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    auth_type: str | None = None
    auth_config: dict[str, Any] | None = None
    secret: str | None = None
    timeout_seconds: int | None = None
    enabled: bool | None = None
    allowed_tools: list[str] | None = None
    tool_permissions: list[ToolPermissionIn] | None = None


class ToolPermissionOut(ORMModel):
    tool_name: str
    permission: str
    enabled: bool


class IntegrationOut(BaseModel):
    id: str
    name: str
    adapter: str
    transport: str
    command: str | None
    args: list[str]
    env: dict[str, str]
    url: str | None
    headers: dict[str, str]
    auth_type: str
    auth_config: dict[str, Any]
    has_secret: bool
    secret_ref: str | None
    timeout_seconds: int
    enabled: bool
    allowed_tools: list[str]
    tool_permissions: list[ToolPermissionOut]
    last_error: str | None
    last_tested_at: str | None
    created_at: str
    updated_at: str
    oauth_authorized: bool = False


class ToolOut(BaseModel):
    name: str
    description: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    permission: str = "read"
    enabled: bool = True


class ConnectionTestOut(BaseModel):
    ok: bool
    message: str
    tools: list[ToolOut] = Field(default_factory=list)
    server_name: str | None = None
    duration_ms: int = 0


class AdapterPresetOut(BaseModel):
    adapter: str
    label: str
    description: str
    transport: str
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    auth_type: str = "none"
    auth_config: dict[str, Any] = Field(default_factory=dict)
    env_hints: dict[str, str] = Field(default_factory=dict)
    tool_permissions: list[ToolPermissionIn] = Field(default_factory=list)
