"""Small shared helpers (ids, time, json)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


_last_timestamp: datetime | None = None
_timestamp_lock = __import__("threading").Lock()


def now_iso() -> str:
    """Current UTC time as ISO-8601 string (stored in SQLite TEXT columns).

    Strictly increasing within the process: rows created in the same clock tick (Windows has
    ~15 ms resolution) still sort in creation order when ordered by their timestamp columns.
    """
    global _last_timestamp
    with _timestamp_lock:
        current = utcnow()
        if _last_timestamp is not None and current <= _last_timestamp:
            current = _last_timestamp + timedelta(microseconds=1)
        _last_timestamp = current
        return current.isoformat()


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def iso_in(**delta: float) -> str:
    return (utcnow() + timedelta(**delta)).isoformat()


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)


def loads(text: str | None, default: Any = None) -> Any:
    if text is None or text == "":
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default
