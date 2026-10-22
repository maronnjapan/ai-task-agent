from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, id_column, ts_column


class ScheduledAction(Base):
    __tablename__ = "scheduled_actions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','done','cancelled')", name="ck_scheduled_actions_status"
        ),
        Index("ix_scheduled_actions_due", "status", "scheduled_at"),
        Index("ix_scheduled_actions_task", "task_id"),
    )

    id: Mapped[str] = id_column()
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True)
    execution_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_plans.id", ondelete="CASCADE"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    scheduled_at: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[str] = ts_column()
    executed_at: Mapped[str | None] = mapped_column(String, nullable=True)


class ManagerSettings(Base):
    __tablename__ = "manager_settings"
    __table_args__ = (
        CheckConstraint(
            "autonomy_level IN ('conservative','balanced','proactive')", name="ck_manager_autonomy"
        ),
        CheckConstraint("reminder_aggressiveness IN ('low','normal','high')", name="ck_manager_reminder"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default="default")
    custom_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    autonomy_level: Mapped[str] = mapped_column(String, nullable=False, default="balanced")
    reminder_aggressiveness: Mapped[str] = mapped_column(String, nullable=False, default="normal")
    updated_at: Mapped[str] = ts_column()


class UserState(Base):
    __tablename__ = "user_state"

    id: Mapped[str] = mapped_column(String, primary_key=True, default="current")
    condition: Mapped[str] = mapped_column(String, nullable=False, default="")
    source: Mapped[str] = mapped_column(String, nullable=False, default="user")
    expires_at: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[str] = ts_column()


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("level IN ('low','normal','high')", name="ck_notifications_level"),
        CheckConstraint("status IN ('unread','read')", name="ck_notifications_status"),
        Index("ix_notifications_created", "created_at"),
        Index("ix_notifications_dedupe", "dedupe_key"),
        Index("ix_notifications_task", "task_id"),
    )

    id: Mapped[str] = id_column()
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    level: Mapped[str] = mapped_column(String, nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String, nullable=False, default="unread")
    channel: Mapped[str] = mapped_column(String, nullable=False, default="in_app")
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="system")
    created_at: Mapped[str] = ts_column()
    read_at: Mapped[str | None] = mapped_column(String, nullable=True)
    delivered_desktop: Mapped[bool] = mapped_column(nullable=False, default=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_created", "created_at"),
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
    )

    id: Mapped[str] = id_column()
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String, nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    actor: Mapped[str] = mapped_column(String, nullable=False, default="system")
    details: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[str] = ts_column()


class AppEvent(Base):
    """Persisted orchestrator trigger queue (SPEC 20.2 / 20.4)."""

    __tablename__ = "app_events"
    __table_args__ = (
        CheckConstraint("status IN ('pending','processed')", name="ck_app_events_status"),
        Index("ix_app_events_status", "status", "created_at"),
    )

    id: Mapped[str] = id_column()
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[str] = ts_column()
    processed_at: Mapped[str | None] = mapped_column(String, nullable=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    updated_at: Mapped[str] = ts_column()


class ApprovalRequest(Base):
    """User approval required before external_write MCP tools run (SPEC 17.14)."""

    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected','expired')", name="ck_approval_requests_status"
        ),
        Index("ix_approval_requests_status", "status"),
        Index("ix_approval_requests_connection", "connection_id"),
    )

    id: Mapped[str] = id_column()
    kind: Mapped[str] = mapped_column(String, nullable=False, default="mcp_tool_call")
    connection_id: Mapped[str | None] = mapped_column(
        ForeignKey("mcp_connections.id", ondelete="CASCADE"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    arguments: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    work_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = ts_column()
    resolved_at: Mapped[str | None] = mapped_column(String, nullable=True)
    executed_at: Mapped[str | None] = mapped_column(String, nullable=True)
