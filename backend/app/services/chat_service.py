"""Chats, messages and formal decisions (SPEC 13, 15)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.events import EventBroker
from app.models import ChatMessage, Task, TaskChat, TaskDecision
from app.models.enums import Actor
from app.services.audit_service import AuditService
from app.services.errors import NotFoundError, ValidationError
from app.utils import now_iso


class ChatService:
    def __init__(self, session: Session, broker: EventBroker | None = None):
        self.session = session
        self.broker = broker
        self.audit = AuditService(session)

    def _task(self, task_id: str) -> Task:
        task = self.session.get(Task, task_id)
        if task is None or task.is_deleted:
            raise NotFoundError("Task not found")
        return task

    def list_chats(self, task_id: str) -> list[tuple[TaskChat, int, str | None]]:
        self._task(task_id)
        rows = self.session.execute(
            select(TaskChat, func.count(ChatMessage.id), func.max(ChatMessage.created_at))
            .outerjoin(ChatMessage, ChatMessage.chat_id == TaskChat.id)
            .where(TaskChat.task_id == task_id)
            .group_by(TaskChat.id)
            .order_by(TaskChat.created_at)
        ).all()
        return [(row[0], int(row[1]), row[2]) for row in rows]

    def get_chat(self, chat_id: str) -> TaskChat:
        chat = self.session.get(TaskChat, chat_id)
        if chat is None:
            raise NotFoundError("Chat not found")
        return chat

    def create_chat(self, task_id: str, title: str | None = None, actor: str = Actor.USER) -> TaskChat:
        self._task(task_id)
        count = self.session.execute(
            select(func.count(TaskChat.id)).where(TaskChat.task_id == task_id)
        ).scalar_one()
        chat = TaskChat(task_id=task_id, title=(title or "").strip() or f"チャット {int(count) + 1}")
        self.session.add(chat)
        self.session.flush()
        self.audit.record("chat.created", "chat", chat.id, actor, {"task_id": task_id})
        if self.broker:
            self.broker.publish("chat.created", {"chat_id": chat.id, "task_id": task_id})
        return chat

    def delete_chat(self, chat_id: str, actor: str = Actor.USER) -> None:
        chat = self.get_chat(chat_id)
        self.session.delete(chat)
        self.session.flush()
        self.audit.record("chat.deleted", "chat", chat_id, actor)

    def list_messages(self, chat_id: str, before: str | None = None, limit: int = 50) -> tuple[list[ChatMessage], bool]:
        """Return messages in chronological order with simple keyset paging."""
        self.get_chat(chat_id)
        stmt = select(ChatMessage).where(ChatMessage.chat_id == chat_id)
        if before:
            anchor = self.session.get(ChatMessage, before)
            if anchor is not None:
                stmt = stmt.where(ChatMessage.created_at < anchor.created_at)
        rows = list(
            self.session.execute(stmt.order_by(ChatMessage.created_at.desc()).limit(limit + 1)).scalars()
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        rows.reverse()
        return rows, has_more

    def recent_messages(self, chat_id: str, limit: int = 30) -> list[ChatMessage]:
        rows, _ = self.list_messages(chat_id, limit=limit)
        return rows

    def add_message(self, chat_id: str, content: str, author_type: str = "user") -> ChatMessage:
        chat = self.get_chat(chat_id)
        if author_type not in ("user", "ai", "system"):
            raise ValidationError("Invalid author_type")
        message = ChatMessage(chat_id=chat.id, author_type=author_type, content=content)
        self.session.add(message)
        self.session.flush()
        if self.broker:
            self.broker.publish(
                "chat.message",
                {"chat_id": chat.id, "task_id": chat.task_id, "message_id": message.id, "author_type": author_type},
            )
        return message

    def search_messages(self, query: str, task_id: str | None = None, limit: int = 20) -> list[ChatMessage]:
        from app.services.memory_service import fts_query

        match = fts_query(query)
        if not match:
            return []
        from sqlalchemy import text

        sql = text(
            "SELECT message_id FROM chat_messages_fts WHERE chat_messages_fts MATCH :q ORDER BY rank LIMIT :limit"
        )
        ids = [row[0] for row in self.session.execute(sql, {"q": match, "limit": limit * 3}).all()]
        if not ids:
            return []
        stmt = select(ChatMessage).join(TaskChat, TaskChat.id == ChatMessage.chat_id).where(ChatMessage.id.in_(ids))
        if task_id:
            stmt = stmt.where(TaskChat.task_id == task_id)
        rows = list(self.session.execute(stmt.limit(limit)).scalars())
        order = {mid: i for i, mid in enumerate(ids)}
        rows.sort(key=lambda m: order.get(m.id, 0))
        return rows


class DecisionService:
    def __init__(self, session: Session, broker: EventBroker | None = None):
        self.session = session
        self.broker = broker
        self.audit = AuditService(session)

    def list(self, task_id: str, include_history: bool = True) -> list[TaskDecision]:
        stmt = select(TaskDecision).where(TaskDecision.task_id == task_id)
        if not include_history:
            stmt = stmt.where(TaskDecision.status == "active")
        return list(self.session.execute(stmt.order_by(TaskDecision.decided_at.desc())).scalars())

    def active(self, task_id: str) -> list[TaskDecision]:
        return list(reversed(self.list(task_id, include_history=False)))

    def get(self, decision_id: str) -> TaskDecision:
        decision = self.session.get(TaskDecision, decision_id)
        if decision is None:
            raise NotFoundError("Decision not found")
        return decision

    def record(
        self,
        task_id: str,
        content: str,
        source_message_id: str | None = None,
        supersedes_id: str | None = None,
        actor: str = Actor.USER,
    ) -> TaskDecision:
        task = self.session.get(Task, task_id)
        if task is None:
            raise NotFoundError("Task not found")
        content = content.strip()
        if not content:
            raise ValidationError("Decision content is required")
        if source_message_id and self.session.get(ChatMessage, source_message_id) is None:
            raise NotFoundError("Source message not found")
        if supersedes_id:
            previous = self.get(supersedes_id)
            if previous.task_id != task_id:
                raise ValidationError("Superseded decision belongs to another task")
            previous.status = "superseded"
        decision = TaskDecision(
            task_id=task_id,
            content=content,
            source_message_id=source_message_id,
            supersedes_id=supersedes_id,
            decided_by=actor,
            decided_at=now_iso(),
        )
        self.session.add(decision)
        self.session.flush()
        self.audit.record("decision.recorded", "decision", decision.id, actor, {"task_id": task_id})
        if self.broker:
            self.broker.publish("decision.recorded", {"task_id": task_id, "decision_id": decision.id})
        return decision

    def revoke(self, decision_id: str, actor: str = Actor.USER) -> TaskDecision:
        decision = self.get(decision_id)
        decision.status = "revoked"
        self.session.flush()
        self.audit.record("decision.revoked", "decision", decision.id, actor)
        return decision
