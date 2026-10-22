"""Long-term memory with FTS5 search (SPEC 14)."""

from __future__ import annotations

import re

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Category, Memory, Task
from app.models.enums import Actor, MemoryKind, MemoryScope
from app.schemas.memories import MemoryCreate, MemoryUpdate
from app.services.audit_service import AuditService
from app.services.errors import NotFoundError, ValidationError
from app.utils import now_iso

_TOKEN = re.compile(r"[\w぀-ヿ㐀-鿿豈-﫿]+", re.UNICODE)


def fts_query(query: str) -> str:
    """Build a safe FTS5 MATCH expression (every term quoted, AND-combined).

    The tables use the ``trigram`` tokenizer so that Japanese and English
    substrings both match; terms shorter than three characters cannot be
    matched by trigrams and are left to the LIKE fallback.
    """
    terms = [t for t in _TOKEN.findall(query or "") if len(t) >= 3]
    if not terms:
        return ""
    return " AND ".join('"' + t.replace('"', '""') + '"' for t in terms[:12])


class MemoryService:
    def __init__(self, session: Session):
        self.session = session
        self.audit = AuditService(session)

    def get(self, memory_id: str) -> Memory:
        memory = self.session.get(Memory, memory_id)
        if memory is None:
            raise NotFoundError("Memory not found")
        return memory

    def _validate_scope(
        self, scope: str, category_id: str | None, task_id: str | None
    ) -> tuple[str | None, str | None]:
        scope = str(scope)
        if scope == MemoryScope.GLOBAL:
            return None, None
        if scope == MemoryScope.CATEGORY:
            if not category_id or self.session.get(Category, category_id) is None:
                raise ValidationError("category_id is required for category memory")
            return category_id, None
        if scope == MemoryScope.TASK:
            task = self.session.get(Task, task_id) if task_id else None
            if task is None:
                raise ValidationError("task_id is required for task memory")
            return task.category_id, task_id
        raise ValidationError("Invalid scope")

    def create(self, data: MemoryCreate, actor: str = Actor.USER) -> Memory:
        category_id, task_id = self._validate_scope(data.scope, data.category_id, data.task_id)
        memory = Memory(
            scope=str(data.scope),
            category_id=category_id,
            task_id=task_id,
            content=data.content.strip(),
            source=data.source,
            kind=str(data.kind),
            confirmed=data.confirmed or data.kind == MemoryKind.DECISION,
        )
        self.session.add(memory)
        self.session.flush()
        self.audit.record(
            "memory.created", "memory", memory.id, actor, {"scope": memory.scope, "kind": memory.kind}
        )
        return memory

    def update(self, memory_id: str, data: MemoryUpdate, actor: str = Actor.USER) -> Memory:
        memory = self.get(memory_id)
        changes = data.model_dump(exclude_unset=True)
        for key, value in changes.items():
            if value is None and key != "source":
                continue
            setattr(memory, key, str(value) if key == "kind" else value)
        memory.updated_at = now_iso()
        self.session.flush()
        self.audit.record("memory.updated", "memory", memory.id, actor, {"fields": list(changes)})
        return memory

    def delete(self, memory_id: str, actor: str = Actor.USER) -> None:
        memory = self.get(memory_id)
        self.session.delete(memory)
        self.session.flush()
        self.audit.record("memory.deleted", "memory", memory_id, actor)

    def list(
        self,
        scope: str | None = None,
        task_id: str | None = None,
        category_id: str | None = None,
        kind: str | None = None,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Memory]:
        if query and query.strip():
            return self.search(
                query, scope=scope, task_id=task_id, category_id=category_id, kind=kind, limit=limit
            )
        stmt = select(Memory)
        if scope:
            stmt = stmt.where(Memory.scope == scope)
        if task_id:
            stmt = stmt.where(Memory.task_id == task_id)
        if category_id:
            stmt = stmt.where(Memory.category_id == category_id)
        if kind:
            stmt = stmt.where(Memory.kind == kind)
        return list(
            self.session.execute(
                stmt.order_by(Memory.updated_at.desc()).limit(limit).offset(offset)
            ).scalars()
        )

    def search(
        self,
        query: str,
        scope: str | None = None,
        task_id: str | None = None,
        category_id: str | None = None,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        match = fts_query(query)
        ids: list[str] = []
        if match:
            sql = text(
                "SELECT memory_id FROM memories_fts WHERE memories_fts MATCH :q ORDER BY rank LIMIT :limit"
            )
            try:
                ids = [row[0] for row in self.session.execute(sql, {"q": match, "limit": limit * 4}).all()]
            except Exception:
                ids = []
        if not ids:
            # Fallback: substring search (handles very short CJK queries).
            return self.search_like(
                query, scope=scope, task_id=task_id, category_id=category_id, kind=kind, limit=limit
            )
        stmt = select(Memory).where(Memory.id.in_(ids))
        if scope:
            stmt = stmt.where(Memory.scope == scope)
        if task_id:
            stmt = stmt.where(Memory.task_id == task_id)
        if category_id:
            stmt = stmt.where(Memory.category_id == category_id)
        if kind:
            stmt = stmt.where(Memory.kind == kind)
        rows = list(self.session.execute(stmt).scalars())
        if not rows:
            # FTS matched only rows outside the requested scope: fall back to a filtered substring search.
            return self.search_like(
                query, scope=scope, task_id=task_id, category_id=category_id, kind=kind, limit=limit
            )
        order = {mid: i for i, mid in enumerate(ids)}
        rows.sort(key=lambda m: order.get(m.id, 0))
        return rows[:limit]

    def search_like(
        self,
        query: str,
        scope: str | None = None,
        task_id: str | None = None,
        category_id: str | None = None,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        like = f"%{query.strip()}%"
        stmt = select(Memory).where(Memory.content.like(like))
        if scope:
            stmt = stmt.where(Memory.scope == scope)
        if task_id:
            stmt = stmt.where(Memory.task_id == task_id)
        if category_id:
            stmt = stmt.where(Memory.category_id == category_id)
        if kind:
            stmt = stmt.where(Memory.kind == kind)
        return list(self.session.execute(stmt.order_by(Memory.updated_at.desc()).limit(limit)).scalars())

    def relevant_for_task(self, task: Task, query: str | None = None, limit: int = 20) -> list[Memory]:
        """Global + category + task memories (SPEC 13.2 / 8.5)."""
        stmt = select(Memory).where(
            (Memory.scope == "global")
            | ((Memory.scope == "category") & (Memory.category_id == task.category_id))
            | ((Memory.scope == "task") & (Memory.task_id == task.id))
        )
        recent = list(self.session.execute(stmt.order_by(Memory.updated_at.desc()).limit(limit)).scalars())
        if not query:
            return recent
        # Query matches come first so they are never cut off by the recency window.
        matched = [
            m
            for m in self.search(query, limit=limit)
            if m.scope == "global"
            or (m.scope == "category" and m.category_id == task.category_id)
            or (m.scope == "task" and m.task_id == task.id)
        ]
        seen = {m.id for m in matched}
        rows = matched + [m for m in recent if m.id not in seen]
        return rows[:limit]

    def global_memories(self, limit: int = 30) -> list[Memory]:
        return list(
            self.session.execute(
                select(Memory).where(Memory.scope == "global").order_by(Memory.updated_at.desc()).limit(limit)
            ).scalars()
        )
