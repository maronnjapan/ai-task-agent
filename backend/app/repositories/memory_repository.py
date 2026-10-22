"""Memory queries including the FTS5 full-text index (SPEC 14.3)."""

from __future__ import annotations

from sqlalchemy import Select, select, text

from app.models import Memory, Task
from app.repositories.base import Repository


class MemoryRepository(Repository):
    def fts_ids(self, match: str, limit: int) -> list[str]:
        """Memory ids ranked by FTS5 relevance; empty when the MATCH expression is invalid."""
        sql = text(
            "SELECT memory_id FROM memories_fts WHERE memories_fts MATCH :q ORDER BY rank LIMIT :limit"
        )
        try:
            return [row[0] for row in self.session.execute(sql, {"q": match, "limit": limit}).all()]
        except Exception:  # noqa: BLE001 - malformed FTS syntax must not break search
            return []

    @staticmethod
    def apply_filters(
        stmt: Select,
        scope: str | None = None,
        task_id: str | None = None,
        category_id: str | None = None,
        kind: str | None = None,
    ) -> Select:
        if scope:
            stmt = stmt.where(Memory.scope == scope)
        if task_id:
            stmt = stmt.where(Memory.task_id == task_id)
        if category_id:
            stmt = stmt.where(Memory.category_id == category_id)
        if kind:
            stmt = stmt.where(Memory.kind == kind)
        return stmt

    def by_ids(self, ids: list[str], **filters) -> list[Memory]:
        if not ids:
            return []
        stmt = self.apply_filters(select(Memory).where(Memory.id.in_(ids)), **filters)
        rows = list(self.session.execute(stmt).scalars())
        order = {mid: i for i, mid in enumerate(ids)}
        rows.sort(key=lambda m: order.get(m.id, 0))
        return rows

    def like(self, query: str, limit: int, **filters) -> list[Memory]:
        stmt = self.apply_filters(select(Memory).where(Memory.content.like(f"%{query.strip()}%")), **filters)
        return list(self.session.execute(stmt.order_by(Memory.updated_at.desc()).limit(limit)).scalars())

    def recent(self, limit: int, offset: int = 0, **filters) -> list[Memory]:
        stmt = self.apply_filters(select(Memory), **filters)
        return list(
            self.session.execute(
                stmt.order_by(Memory.updated_at.desc()).limit(limit).offset(offset)
            ).scalars()
        )

    def scoped_for_task(self, task: Task, limit: int) -> list[Memory]:
        """Global + the task's category + the task itself (SPEC 14.1)."""
        stmt = select(Memory).where(
            (Memory.scope == "global")
            | ((Memory.scope == "category") & (Memory.category_id == task.category_id))
            | ((Memory.scope == "task") & (Memory.task_id == task.id))
        )
        return list(self.session.execute(stmt.order_by(Memory.updated_at.desc()).limit(limit)).scalars())

    def by_category(self, category_id: str) -> list[Memory]:
        return list(self.session.execute(select(Memory).where(Memory.category_id == category_id)).scalars())
