"""In-process event broker used for Server-Sent Events (SPEC 22.6 / 25)."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from app.utils import now_iso

log = logging.getLogger(__name__)


@dataclass
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)
    id: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "data": self.data, "created_at": self.created_at}


class EventBroker:
    """Thread-safe publish/subscribe broker.

    ``publish`` may be called from any thread (services run in the FastAPI
    threadpool as well as from the orchestrator task). Subscribers are
    asyncio queues bound to the event loop that called ``subscribe``.
    """

    def __init__(self, history: int = 200):
        self._subscribers: dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Queue[Event]]] = {}
        self._lock = threading.Lock()
        self._counter = 0
        self._history: deque[Event] = deque(maxlen=history)
        self._listeners: list[Any] = []

    def add_listener(self, callback: Any) -> None:
        """Synchronous listener invoked on publish (used by the orchestrator)."""
        self._listeners.append(callback)

    def publish(self, event_type: str, data: dict[str, Any] | None = None) -> Event:
        with self._lock:
            self._counter += 1
            event = Event(type=event_type, data=data or {}, id=self._counter)
            self._history.append(event)
            targets = list(self._subscribers.values())
        for loop, queue in targets:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:
                pass
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:  # pragma: no cover - listeners must not break publishing
                log.exception("event listener failed")
        return event

    def subscribe(self) -> tuple[int, asyncio.Queue[Event]]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Event] = asyncio.Queue()
        with self._lock:
            self._counter += 0
            token = id(queue)
            self._subscribers[token] = (loop, queue)
        return token, queue

    def unsubscribe(self, token: int) -> None:
        with self._lock:
            self._subscribers.pop(token, None)

    def history(self, since_id: int = 0) -> list[Event]:
        with self._lock:
            return [e for e in self._history if e.id > since_id]

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
