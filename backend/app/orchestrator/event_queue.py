"""Persisted trigger queue for the orchestrator (SPEC 20.2, 20.4)."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.database import Database
from app.models import AppEvent
from app.utils import dumps, loads, now_iso

TRIGGERS = {
    "app_started",
    "task_created",
    "task_updated",
    "user_instruction",
    "work_item_completed",
    "review_completed",
    "schedule_due",
    "user_approved",
    "manual_run",
    "approval_resolved",
    "reevaluate",
}


@dataclass
class Trigger:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str | None = None


class EventQueue:
    """Hybrid queue: events are persisted to ``app_events`` and signalled in memory."""

    def __init__(self, db: Database):
        self.db = db
        self._wakeup: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._wakeup = asyncio.Event()

    def push(
        self, event_type: str, payload: dict[str, Any] | None = None, session: Session | None = None
    ) -> str:
        if session is not None:
            row = AppEvent(event_type=event_type, payload=dumps(payload or {}))
            session.add(row)
            session.flush()
            event_id = row.id
        else:
            with self.db.session() as s:
                row = AppEvent(event_type=event_type, payload=dumps(payload or {}))
                s.add(row)
                s.flush()
                event_id = row.id
        self.wake()
        return event_id

    def wake(self) -> None:
        loop, wakeup = self._loop, self._wakeup
        if loop is None or wakeup is None:
            return
        try:
            loop.call_soon_threadsafe(wakeup.set)
        except RuntimeError:
            pass

    async def wait(self, timeout: float | None) -> bool:
        assert self._wakeup is not None
        try:
            await asyncio.wait_for(self._wakeup.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False
        finally:
            self._wakeup.clear()

    def drain(self) -> list[Trigger]:
        """Return and mark processed all pending events (oldest first)."""
        with self.db.session() as session:
            rows = list(
                session.execute(
                    select(AppEvent).where(AppEvent.status == "pending").order_by(AppEvent.created_at)
                ).scalars()
            )
            triggers = []
            for row in rows:
                triggers.append(Trigger(type=row.event_type, payload=loads(row.payload, {}) or {}, id=row.id))
                row.status = "processed"
                row.processed_at = now_iso()
            return triggers

    def pending_count(self) -> int:
        from sqlalchemy import func

        with self.db.session() as session:
            return int(
                session.execute(
                    select(func.count(AppEvent.id)).where(AppEvent.status == "pending")
                ).scalar_one()
            )
