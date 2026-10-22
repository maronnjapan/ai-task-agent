from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, id_column, ts_column


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[str] = id_column()
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[str] = ts_column()

    tasks: Mapped[list[Task]] = relationship(back_populates="category")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("status IN ('todo','in_progress','review_pending','blocked','completed')", name="ck_tasks_status"),
        CheckConstraint("assignee IN ('user','ai','shared')", name="ck_tasks_assignee"),
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_due_at", "due_at"),
        Index("ix_tasks_category", "category_id"),
        Index("ix_tasks_deleted", "is_deleted"),
    )

    id: Mapped[str] = id_column()
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[str | None] = mapped_column(String, nullable=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="todo")
    assignee: Mapped[str] = mapped_column(String, nullable=False, default="shared")
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = ts_column()
    updated_at: Mapped[str] = ts_column()

    category: Mapped[Category | None] = relationship(back_populates="tasks")
    versions: Mapped[list[TaskVersion]] = relationship(back_populates="task", cascade="all, delete-orphan")
    chats: Mapped[list[TaskChat]] = relationship(back_populates="task", cascade="all, delete-orphan")
    decisions: Mapped[list[TaskDecision]] = relationship(back_populates="task", cascade="all, delete-orphan")
    contexts: Mapped[list[TaskContext]] = relationship(back_populates="task", cascade="all, delete-orphan")


class TaskVersion(Base):
    __tablename__ = "task_versions"
    __table_args__ = (
        UniqueConstraint("task_id", "version", name="uq_task_versions_task_version"),
        CheckConstraint("changed_by IN ('user','ai','system')", name="ck_task_versions_changed_by"),
    )

    id: Mapped[str] = id_column()
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    revised_content: Mapped[str] = mapped_column(Text, nullable=False)  # JSON snapshot after the change
    previous_content: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON snapshot before the change
    changed_by: Mapped[str] = mapped_column(String, nullable=False, default="user")
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = ts_column()

    task: Mapped[Task] = relationship(back_populates="versions")


class TaskContext(Base):
    __tablename__ = "task_contexts"
    __table_args__ = (CheckConstraint("status IN ('open','resolved')", name="ck_task_contexts_status"),)

    id: Mapped[str] = id_column()
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    context: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    created_at: Mapped[str] = ts_column()

    task: Mapped[Task] = relationship(back_populates="contexts")


class TaskDecision(Base):
    __tablename__ = "task_decisions"
    __table_args__ = (CheckConstraint("status IN ('active','superseded','revoked')", name="ck_task_decisions_status"),)

    id: Mapped[str] = id_column()
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("task_decisions.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    decided_by: Mapped[str] = mapped_column(String, nullable=False, default="user")
    decided_at: Mapped[str] = ts_column()

    task: Mapped[Task] = relationship(back_populates="decisions")


class TaskChat(Base):
    __tablename__ = "task_chats"

    id: Mapped[str] = id_column()
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = ts_column()

    task: Mapped[Task] = relationship(back_populates="chats")
    messages: Mapped[list[ChatMessage]] = relationship(back_populates="chat", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("author_type IN ('user','ai','system')", name="ck_chat_messages_author"),
        Index("ix_chat_messages_chat_created", "chat_id", "created_at"),
    )

    id: Mapped[str] = id_column()
    chat_id: Mapped[str] = mapped_column(ForeignKey("task_chats.id", ondelete="CASCADE"), nullable=False)
    author_type: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = ts_column()

    chat: Mapped[TaskChat] = relationship(back_populates="messages")
