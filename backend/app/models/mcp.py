from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, id_column, ts_column


class MCPConnection(Base):
    __tablename__ = "mcp_connections"
    __table_args__ = (
        CheckConstraint("transport IN ('stdio','streamable_http')", name="ck_mcp_connections_transport"),
        CheckConstraint(
            "auth_type IN ('none','api_token','bearer','oauth2','custom')", name="ck_mcp_connections_auth_type"
        ),
    )

    id: Mapped[str] = id_column()
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    adapter: Mapped[str] = mapped_column(String, nullable=False, default="generic")  # generic|slack|google_drive|...
    transport: Mapped[str] = mapped_column(String, nullable=False, default="stdio")
    command: Mapped[str | None] = mapped_column(String, nullable=True)
    args: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list
    env: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON dict (non-secret values only)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    headers: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON dict
    auth_type: Mapped[str] = mapped_column(String, nullable=False, default="none")
    auth_config: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON (non-secret OAuth settings)
    secret_ref: Mapped[str | None] = mapped_column(String, nullable=True)  # name in the Secret Provider
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allowed_tools: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list; empty = all
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_tested_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = ts_column()
    updated_at: Mapped[str] = ts_column()

    tool_permissions: Mapped[list[MCPToolPermission]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )


class MCPToolPermission(Base):
    __tablename__ = "mcp_tool_permissions"
    __table_args__ = (
        CheckConstraint(
            "permission IN ('read','internal_write','external_write')", name="ck_mcp_tool_permissions_permission"
        ),
    )

    connection_id: Mapped[str] = mapped_column(ForeignKey("mcp_connections.id", ondelete="CASCADE"), primary_key=True)
    tool_name: Mapped[str] = mapped_column(String, primary_key=True)
    permission: Mapped[str] = mapped_column(String, nullable=False, default="read")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    connection: Mapped[MCPConnection] = relationship(back_populates="tool_permissions")
