from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, id_column, ts_column


class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (
        CheckConstraint("scope IN ('global','category','task')", name="ck_memories_scope"),
        CheckConstraint("kind IN ('hypothesis','ai_inference','research','decision')", name="ck_memories_kind"),
        # scope / reference consistency (SPEC 23.4)
        CheckConstraint(
            "(scope = 'global' AND category_id IS NULL AND task_id IS NULL) OR "
            "(scope = 'category' AND category_id IS NOT NULL AND task_id IS NULL) OR "
            "(scope = 'task' AND task_id IS NOT NULL)",
            name="ck_memories_scope_reference",
        ),
        Index("ix_memories_scope", "scope"),
        Index("ix_memories_task", "task_id"),
        Index("ix_memories_category", "category_id"),
    )

    id: Mapped[str] = id_column()
    scope: Mapped[str] = mapped_column(String, nullable=False)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), nullable=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="research")
    confirmed: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[str] = ts_column()
    updated_at: Mapped[str] = ts_column()
