"""CRUD for MCP connections (SPEC 17.3, 17.13)."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.logging import register_secret
from app.infrastructure.secrets.base import SecretProvider
from app.integrations.mcp.config import SECRET_PLACEHOLDER, ConnectionConfig
from app.integrations.permissions import validate_permission
from app.models import MCPConnection, MCPToolPermission
from app.schemas.integrations import IntegrationCreate, IntegrationUpdate
from app.services.audit_service import AuditService
from app.services.errors import NotFoundError, ValidationError
from app.utils import dumps, now_iso

TRANSPORTS = {"stdio", "streamable_http"}
AUTH_TYPES = {"none", "api_token", "bearer", "oauth2", "custom"}
SECRET_KEY_PATTERN = re.compile(
    r"(token|secret|key|password|passwd|credential|authorization|cookie|auth)", re.IGNORECASE
)


def is_secret_key(key: str) -> bool:
    return bool(SECRET_KEY_PATTERN.search(key or ""))


class IntegrationService:
    def __init__(self, session: Session, secret_store: SecretProvider):
        self.session = session
        self.secret_store = secret_store
        self.audit = AuditService(session)

    def list(self) -> list[MCPConnection]:
        return list(self.session.execute(select(MCPConnection).order_by(MCPConnection.name)).scalars())

    def get(self, connection_id: str) -> MCPConnection:
        row = self.session.get(MCPConnection, connection_id)
        if row is None:
            raise NotFoundError("Integration not found")
        return row

    def _validate(self, transport: str, auth_type: str, command: str | None, url: str | None) -> None:
        if transport not in TRANSPORTS:
            raise ValidationError("transport must be stdio or streamable_http")
        if auth_type not in AUTH_TYPES:
            raise ValidationError("unsupported auth_type")
        if transport == "stdio" and not command:
            raise ValidationError("command is required for stdio")
        if transport == "streamable_http" and not url:
            raise ValidationError("url is required for streamable_http")

    def create(self, data: IntegrationCreate, actor: str = "user") -> MCPConnection:
        self._validate(data.transport, data.auth_type, data.command, data.url)
        if self.session.execute(
            select(MCPConnection).where(MCPConnection.name == data.name)
        ).scalar_one_or_none():
            raise ValidationError("An integration with that name already exists")
        row = MCPConnection(
            name=data.name.strip(),
            adapter=data.adapter or "generic",
            transport=data.transport,
            command=data.command,
            args=dumps(data.args),
            env=dumps(data.env),
            url=data.url,
            headers=dumps(data.headers),
            auth_type=data.auth_type,
            auth_config=dumps(data.auth_config),
            timeout_seconds=data.timeout_seconds,
            enabled=data.enabled,
            allowed_tools=dumps(data.allowed_tools),
        )
        self.session.add(row)
        self.session.flush()
        config = ConnectionConfig.from_model(row)
        row.secret_ref = config.secret_name()
        if data.secret:
            self.secret_store.set_secret(row.secret_ref, data.secret)
            register_secret(data.secret)
        row.env = dumps(self._protect(config, data.env, "env"))
        row.headers = dumps(self._protect(config, data.headers, "header"))
        self._set_permissions(row, [p.model_dump() for p in data.tool_permissions])
        self.session.flush()
        self.audit.record(
            "mcp.created", "mcp_connection", row.id, actor, {"name": row.name, "transport": row.transport}
        )
        return row

    def update(self, connection_id: str, data: IntegrationUpdate, actor: str = "user") -> MCPConnection:
        row = self.get(connection_id)
        changes = data.model_dump(exclude_unset=True)
        secret = changes.pop("secret", None)
        permissions = changes.pop("tool_permissions", None)
        config = ConnectionConfig.from_model(row)
        if changes.get("env") is not None:
            changes["env"] = self._protect(config, changes["env"], "env")
        if changes.get("headers") is not None:
            changes["headers"] = self._protect(config, changes["headers"], "header")
        for key in ("args", "env", "headers", "auth_config", "allowed_tools"):
            if key in changes and changes[key] is not None:
                changes[key] = dumps(changes[key])
        for key, value in changes.items():
            if value is None and key in (
                "name",
                "adapter",
                "transport",
                "auth_type",
                "timeout_seconds",
                "enabled",
            ):
                continue
            setattr(row, key, value)
        self._validate(row.transport, row.auth_type, row.command, row.url)
        if secret:
            self.secret_store.set_secret(row.secret_ref or config.secret_name(), secret)
            register_secret(secret)
        if permissions is not None:
            self._set_permissions(row, permissions)
        row.updated_at = now_iso()
        self.session.flush()
        self.audit.record("mcp.updated", "mcp_connection", row.id, actor, {"fields": list(changes)})
        return row

    def _protect(self, config: ConnectionConfig, values: dict[str, str], kind: str) -> dict[str, str]:
        """Store secret-looking values (tokens, keys, Authorization...) in the Secret Provider.

        SQLite only keeps the placeholder, and the API never returns the real value (SPEC 17.6 / 27.2).
        """
        protected: dict[str, str] = {}
        for key, value in (values or {}).items():
            value = "" if value is None else str(value)
            name = config.env_secret_name(key) if kind == "env" else config.header_secret_name(key)
            if not is_secret_key(key):
                protected[key] = value
                continue
            if value == SECRET_PLACEHOLDER:
                protected[key] = SECRET_PLACEHOLDER  # unchanged, keep the stored secret
                continue
            if value == "":
                self.secret_store.delete_secret(name)
                continue
            self.secret_store.set_secret(name, value)
            register_secret(value)
            protected[key] = SECRET_PLACEHOLDER
        return protected

    def delete(self, connection_id: str, actor: str = "user") -> None:
        row = self.get(connection_id)
        config = ConnectionConfig.from_model(row)
        for key, value in config.env.items():
            if value == SECRET_PLACEHOLDER:
                self.secret_store.delete_secret(config.env_secret_name(key))
        for key, value in config.headers.items():
            if value == SECRET_PLACEHOLDER:
                self.secret_store.delete_secret(config.header_secret_name(key))
        for name in (config.secret_name(), config.oauth_secret_name()):
            try:
                self.secret_store.delete_secret(name)
            except Exception:  # noqa: BLE001
                pass
        self.session.delete(row)
        self.session.flush()
        self.audit.record("mcp.deleted", "mcp_connection", connection_id, actor)

    def _set_permissions(self, row: MCPConnection, permissions: list[dict]) -> None:
        existing = {p.tool_name: p for p in row.tool_permissions}
        for spec in permissions:
            name = str(spec.get("tool_name") or "").strip()
            if not name:
                continue
            permission = validate_permission(str(spec.get("permission", "read")))
            enabled = bool(spec.get("enabled", True))
            if name in existing:
                existing[name].permission = permission
                existing[name].enabled = enabled
            else:
                self.session.add(
                    MCPToolPermission(
                        connection_id=row.id, tool_name=name, permission=permission, enabled=enabled
                    )
                )
        self.session.flush()

    def has_secret(self, row: MCPConnection) -> bool:
        return bool(row.secret_ref and self.secret_store.get_secret(row.secret_ref))
