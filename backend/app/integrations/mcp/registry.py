"""Connection registry: configuration, live clients, permissions and approvals (SPEC 17.3, 17.13, 17.14)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from langchain_core.tools import BaseTool, StructuredTool
from sqlalchemy import select

from app.integrations.mcp.adapters import get_adapter
from app.integrations.mcp.authentication import OAuth2Auth, OAuthFlowManager, build_auth
from app.integrations.mcp.client import MCPClient, MCPConnectionError, ToolInfo, ToolResult
from app.integrations.mcp.config import ConnectionConfig
from app.integrations.permissions import requires_approval
from app.models import MCPConnection
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.utils import now_iso

if TYPE_CHECKING:  # pragma: no cover
    from app.agents.context import AgentContext
    from app.context import AppContext

log = logging.getLogger(__name__)


class PermissionDeniedError(PermissionError):
    pass


class ApprovalPendingError(RuntimeError):
    def __init__(self, approval_id: str, message: str):
        super().__init__(message)
        self.approval_id = approval_id


class MCPRegistry:
    def __init__(
        self, app: AppContext, approval_wait_seconds: float = 0.0, approval_poll_seconds: float = 2.0
    ):
        self.app = app
        self._clients: dict[str, MCPClient] = {}
        self._auth: dict[str, Any] = {}
        self.oauth_flows = OAuthFlowManager()
        self.approval_wait_seconds = approval_wait_seconds
        self.approval_poll_seconds = approval_poll_seconds
        self.http_post = None  # injectable for OAuth tests

    # --- configuration ------------------------------------------------
    def configs(self, enabled_only: bool = True) -> list[ConnectionConfig]:
        with self.app.db.session() as session:
            stmt = select(MCPConnection).order_by(MCPConnection.name)
            if enabled_only:
                stmt = stmt.where(MCPConnection.enabled.is_(True))
            return [ConnectionConfig.from_model(row) for row in session.execute(stmt).scalars()]

    def config(self, connection_id: str) -> ConnectionConfig:
        with self.app.db.session() as session:
            row = session.get(MCPConnection, connection_id)
            if row is None:
                raise KeyError(connection_id)
            return ConnectionConfig.from_model(row)

    def auth_for(self, config: ConnectionConfig):
        auth = self._auth.get(config.id)
        if auth is None or getattr(auth, "auth_type", None) != config.auth_type:
            auth = build_auth(config, self.app.secret_store, http_post=self.http_post)
            self._auth[config.id] = auth
        return auth

    def invalidate(self, connection_id: str) -> None:
        self._auth.pop(connection_id, None)
        client = self._clients.pop(connection_id, None)
        if client is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(client.disconnect())
            except RuntimeError:
                pass

    async def shutdown(self) -> None:
        for client in list(self._clients.values()):
            await client.disconnect()
        self._clients.clear()

    # --- clients ------------------------------------------------------
    async def client(self, connection_id: str, config: ConnectionConfig | None = None) -> MCPClient:
        config = config or self.config(connection_id)
        client = self._clients.get(connection_id)
        if client is None or client.config != config or not client.connected:
            if client is not None:
                await client.disconnect()
            client = MCPClient(config, auth=self.auth_for(config))
            await client.connect()
            self._clients[connection_id] = client
        return client

    async def test_connection(self, config: ConnectionConfig) -> dict[str, Any]:
        started = time.monotonic()
        client = MCPClient(config, auth=self.auth_for(config))
        try:
            await client.connect()
            tools = await client.list_tools()
            message = f"接続に成功しました（ツール {len(tools)} 件）"
            ok = True
            server_name = client.server_info.get("name")
        except Exception as exc:  # noqa: BLE001
            tools, ok, message, server_name = (
                [],
                False,
                get_adapter(config.adapter).translate_error(exc),
                None,
            )
        finally:
            await client.disconnect()
        duration = int((time.monotonic() - started) * 1000)
        with self.app.db.session() as session:
            row = session.get(MCPConnection, config.id)
            if row is not None:
                row.last_error = None if ok else message
                row.last_tested_at = now_iso()
            AuditService(session).record(
                "mcp.test", "mcp_connection", config.id, "user", {"ok": ok, "message": message}
            )
        return {
            "ok": ok,
            "message": message,
            "tools": [self.describe_tool(config, t) for t in tools],
            "server_name": server_name,
            "duration_ms": duration,
        }

    async def list_tools(self, connection_id: str) -> list[dict[str, Any]]:
        config = self.config(connection_id)
        client = await self.client(connection_id, config)
        tools = await client.list_tools(use_cache=False)
        return [self.describe_tool(config, t) for t in tools]

    def describe_tool(self, config: ConnectionConfig, tool: ToolInfo) -> dict[str, Any]:
        permission, enabled = self.permission_for(config, tool)
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
            "permission": permission,
            "enabled": enabled,
        }

    def permission_for(self, config: ConnectionConfig, tool: ToolInfo) -> tuple[str, bool]:
        explicit = config.tool_permissions.get(tool.name)
        if explicit:
            return explicit
        enabled = not config.allowed_tools or tool.name in config.allowed_tools
        return get_adapter(config.adapter).classify(tool), enabled

    # --- tool execution with permission enforcement --------------------
    async def call_tool(
        self,
        connection_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        agent_ctx: AgentContext | None = None,
        reason: str | None = None,
    ) -> ToolResult:
        config = self.config(connection_id)
        if not config.enabled:
            raise PermissionDeniedError(f"connection {config.name} is disabled")
        adapter = get_adapter(config.adapter)
        client = await self.client(connection_id, config)
        tools = await client.list_tools()
        real_name = adapter.map_tool_name(tool_name)
        info = next((t for t in tools if t.name in (tool_name, real_name)), None)
        if info is None:
            raise MCPConnectionError(f"tool {tool_name} not found on {config.name}")
        permission, enabled = self.permission_for(config, info)
        if not enabled:
            raise PermissionDeniedError(f"tool {info.name} is disabled for {config.name}")
        if requires_approval(permission):
            await self._require_approval(config, info.name, arguments, agent_ctx, reason)
        arguments = adapter.transform_args(info.name, arguments)
        try:
            result = await client.call_tool(info.name, arguments)
        except Exception as exc:  # noqa: BLE001
            delay = adapter.rate_limit_delay(exc)
            if delay is not None and delay <= 30:
                await asyncio.sleep(delay)
                result = await client.call_tool(info.name, arguments)
            else:
                raise MCPConnectionError(adapter.translate_error(exc)) from exc
        with self.app.db.session() as session:
            AuditService(session).record(
                "mcp.tool_call",
                "mcp_connection",
                config.id,
                "ai",
                {"tool": info.name, "permission": permission, "is_error": result.is_error},
            )
        return result

    async def _require_approval(
        self,
        config: ConnectionConfig,
        tool_name: str,
        arguments: dict[str, Any],
        agent_ctx: AgentContext | None,
        reason: str | None,
    ) -> None:
        with self.app.db.session() as session:
            approvals = ApprovalService(session, self.app.broker)
            request = approvals.request(
                tool_name,
                arguments,
                connection_id=config.id,
                task_id=(agent_ctx.task_ids[0] if agent_ctx and agent_ctx.task_ids else None),
                work_item_id=agent_ctx.work_item_id if agent_ctx else None,
                reason=reason or f"{config.name} への外部書き込み",
            )
            approval_id = request.id
        deadline = time.monotonic() + self.approval_wait_seconds
        while True:
            with self.app.db.session() as session:
                row = ApprovalService(session).get(approval_id)
                status = row.status
            if status == "approved":
                return
            if status in ("rejected", "expired"):
                raise PermissionDeniedError(f"user rejected {tool_name} on {config.name}")
            if time.monotonic() >= deadline:
                raise ApprovalPendingError(
                    approval_id,
                    f"{tool_name} requires user approval (request {approval_id}); the work item should report blocked until it is approved",
                )
            await asyncio.sleep(self.approval_poll_seconds)

    # --- service search (Slack / Drive / Confluence / Jira) ------------
    def connection_for_adapter(self, adapter_name: str) -> ConnectionConfig | None:
        for config in self.configs():
            if config.adapter == adapter_name:
                return config
        return None

    async def search_service(
        self, adapter_name: str, query: str, limit: int = 10, agent_ctx: AgentContext | None = None
    ) -> list[dict[str, Any]]:
        config = self.connection_for_adapter(adapter_name)
        if config is None:
            raise MCPConnectionError(f"no enabled {adapter_name} connection is configured")
        adapter = get_adapter(adapter_name)
        client = await self.client(config.id, config)
        tools = await client.list_tools()
        tool = adapter.pick_search_tool(tools)
        if tool is None:
            raise MCPConnectionError(f"{config.name} exposes no search tool")
        args = adapter.build_search_args(tool, query, limit)
        result = await self.call_tool(config.id, tool.name, args, agent_ctx=agent_ctx)
        if result.is_error:
            raise MCPConnectionError(result.text[:500])
        return adapter.normalize_results(tool.name, result)[:limit]

    # --- LangChain tool exposure (SPEC 26: MCP由来のツールは動的に追加) ----
    async def langchain_tools(self, agent_ctx: AgentContext) -> list[BaseTool]:
        tools: list[BaseTool] = []
        for config in self.configs():
            try:
                client = await self.client(config.id, config)
                infos = await client.list_tools()
            except Exception as exc:  # noqa: BLE001
                log.warning("MCP connection %s unavailable: %s", config.name, exc)
                with self.app.db.session() as session:
                    row = session.get(MCPConnection, config.id)
                    if row is not None:
                        row.last_error = str(exc)[:500]
                continue
            for info in infos:
                permission, enabled = self.permission_for(config, info)
                if not enabled:
                    continue
                tools.append(self._make_langchain_tool(config, info, permission, agent_ctx))
        return tools

    def _make_langchain_tool(
        self, config: ConnectionConfig, info: ToolInfo, permission: str, agent_ctx: AgentContext
    ) -> BaseTool:
        from pydantic import Field, create_model

        connection_id, tool_name = config.id, info.name
        fields: dict[str, Any] = {}
        props = (info.input_schema or {}).get("properties", {}) if isinstance(info.input_schema, dict) else {}
        required = set(
            (info.input_schema or {}).get("required", []) if isinstance(info.input_schema, dict) else []
        )
        for key, spec in props.items():
            description = spec.get("description", "") if isinstance(spec, dict) else ""
            fields[key] = (Any, Field(default=... if key in required else None, description=description))
        safe = "".join(ch if ch.isalnum() else "_" for ch in f"mcp_{config.name}_{tool_name}")[:64]
        args_model = create_model(f"{safe}_args", **fields) if fields else None

        async def _call(**kwargs: Any) -> str:
            arguments = {k: v for k, v in kwargs.items() if v is not None}
            try:
                result = await self.call_tool(connection_id, tool_name, arguments, agent_ctx=agent_ctx)
            except ApprovalPendingError as exc:
                return f"approval_required: {exc}"
            except (PermissionDeniedError, MCPConnectionError) as exc:
                return f"error: {exc}"
            from app.agents.context import wrap_external

            return wrap_external(result.text if not result.is_error else f"error: {result.text}")

        description = f"[{config.name} / {permission}] {info.description or tool_name}"
        if requires_approval(permission):
            description += " (requires user approval before execution)"
        return StructuredTool.from_function(
            coroutine=_call,
            name=safe,
            description=description[:1000],
            args_schema=args_model,
            infer_schema=args_model is None,
        )

    # --- OAuth helpers -------------------------------------------------
    def begin_oauth(self, connection_id: str) -> dict[str, str]:
        config = self.config(connection_id)
        auth = self.auth_for(config)
        if not isinstance(auth, OAuth2Auth):
            raise ValueError("connection does not use oauth2")
        pending = self.oauth_flows.begin(connection_id)
        url = auth.authorization_url(pending.state, pending.code_verifier)
        return {"authorization_url": url, "state": pending.state}

    async def complete_oauth(self, state: str, code: str) -> str:
        pending = self.oauth_flows.take(state)
        if pending is None:
            raise ValueError("unknown or expired OAuth state")
        config = self.config(pending.connection_id)
        auth = self.auth_for(config)
        if not isinstance(auth, OAuth2Auth):
            raise ValueError("connection does not use oauth2")
        await auth.exchange_code(code, pending.code_verifier)
        self.invalidate_client_only(pending.connection_id)
        with self.app.db.session() as session:
            AuditService(session).record("mcp.oauth_authorized", "mcp_connection", config.id, "user")
        return pending.connection_id

    def invalidate_client_only(self, connection_id: str) -> None:
        client = self._clients.pop(connection_id, None)
        if client is not None:
            try:
                asyncio.get_running_loop().create_task(client.disconnect())
            except RuntimeError:
                pass

    def oauth_authorized(self, config: ConnectionConfig) -> bool:
        if config.auth_type != "oauth2":
            return False
        auth = self.auth_for(config)
        return bool(getattr(auth, "is_ready", lambda: False)())
