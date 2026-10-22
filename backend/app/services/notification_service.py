"""Proactive notifications with suppression rules (SPEC 18)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.events import EventBroker
from app.models import Notification
from app.models.enums import NotificationLevel
from app.platform.base import PlatformAdapter
from app.schemas.settings import NotificationSettings
from app.services.audit_service import AuditService
from app.services.errors import NotFoundError
from app.utils import now_iso, parse_iso, utcnow

log = logging.getLogger(__name__)

_LEVEL_RANK = {"low": 0, "normal": 1, "high": 2}
RATE_LIMIT_EXEMPT = {"scheduler", "user", "system"}


def in_quiet_hours(now_local: datetime, start: str | None, end: str | None) -> bool:
    if not start or not end:
        return False
    try:
        sh, sm = (int(x) for x in start.split(":"))
        eh, em = (int(x) for x in end.split(":"))
    except ValueError:
        return False
    current = now_local.hour * 60 + now_local.minute
    start_m = sh * 60 + sm
    end_m = eh * 60 + em
    if start_m == end_m:
        return False
    if start_m < end_m:
        return start_m <= current < end_m
    return current >= start_m or current < end_m


class NotificationService:
    def __init__(
        self,
        session: Session,
        settings: NotificationSettings | None = None,
        platform: PlatformAdapter | None = None,
        broker: EventBroker | None = None,
    ):
        self.session = session
        self.settings = settings or NotificationSettings()
        self.platform = platform
        self.broker = broker
        self.audit = AuditService(session)

    def list(self, unread_only: bool = False, limit: int = 50, offset: int = 0) -> tuple[list[Notification], int]:
        stmt = select(Notification)
        if unread_only:
            stmt = stmt.where(Notification.status == "unread")
        total = self.session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        rows = self.session.execute(stmt.order_by(Notification.created_at.desc()).limit(limit).offset(offset)).scalars().all()
        return list(rows), int(total)

    def unread_count(self) -> int:
        return int(self.session.execute(select(func.count(Notification.id)).where(Notification.status == "unread")).scalar_one())

    def get(self, notification_id: str) -> Notification:
        row = self.session.get(Notification, notification_id)
        if row is None:
            raise NotFoundError("Notification not found")
        return row

    def mark_read(self, ids: list[str] | None = None) -> int:
        stmt = select(Notification).where(Notification.status == "unread")
        if ids:
            stmt = stmt.where(Notification.id.in_(ids))
        count = 0
        for row in self.session.execute(stmt).scalars():
            row.status = "read"
            row.read_at = now_iso()
            count += 1
        self.session.flush()
        if count and self.broker:
            self.broker.publish("notification.read", {"count": count})
        return count

    def _suppressed(self, dedupe_key: str | None, level: str, source: str = "system") -> str | None:
        now = utcnow()
        if dedupe_key and self.settings.dedupe_window_minutes > 0:
            since = (now - timedelta(minutes=self.settings.dedupe_window_minutes)).isoformat()
            dup = self.session.execute(
                select(Notification.id).where(Notification.dedupe_key == dedupe_key, Notification.created_at >= since).limit(1)
            ).scalar_one_or_none()
            if dup:
                return "duplicate"
        # Deterministic reminders (scheduler) are de-duplicated per task/day instead of rate limited.
        if self.settings.min_interval_seconds > 0 and level != NotificationLevel.HIGH and source not in RATE_LIMIT_EXEMPT:
            since = (now - timedelta(seconds=self.settings.min_interval_seconds)).isoformat()
            recent = self.session.execute(
                select(Notification.id).where(Notification.created_at >= since, Notification.source.notin_(list(RATE_LIMIT_EXEMPT))).limit(1)
            ).scalar_one_or_none()
            if recent:
                return "rate_limited"
        return None

    def create(
        self,
        title: str,
        body: str = "",
        level: str = "normal",
        task_id: str | None = None,
        dedupe_key: str | None = None,
        source: str = "system",
        channel: str = "in_app",
        force: bool = False,
    ) -> Notification | None:
        level = str(NotificationLevel(level))
        reason = None if force else self._suppressed(dedupe_key, level, source)
        if reason:
            log.debug("notification suppressed (%s): %s", reason, title)
            self.audit.record("notification.suppressed", "notification", None, "system", {"title": title, "reason": reason})
            return None
        row = Notification(
            title=title.strip()[:200],
            body=body or "",
            level=level,
            task_id=task_id,
            dedupe_key=dedupe_key,
            source=source,
            channel=channel,
        )
        self.session.add(row)
        self.session.flush()
        self.audit.record("notification.created", "notification", row.id, source, {"title": row.title, "level": level})
        if self.broker:
            self.broker.publish(
                "notification.created",
                {"notification_id": row.id, "title": row.title, "body": row.body, "level": level, "task_id": task_id},
            )
        if self._should_deliver_desktop(level):
            try:
                delivered = self.platform.show_notification(row.title, row.body) if self.platform else False
            except Exception:  # pragma: no cover - platform specific
                log.exception("desktop notification failed")
                delivered = False
            row.delivered_desktop = bool(delivered)
            if delivered:
                row.channel = "desktop"
        return row

    def _should_deliver_desktop(self, level: str) -> bool:
        if not self.settings.desktop_enabled or self.platform is None:
            return False
        threshold = {"low": 2, "normal": 1, "high": 0}.get(self.settings.level, 1)
        if _LEVEL_RANK.get(level, 1) < threshold:
            return False
        local_now = datetime.now().astimezone()
        if in_quiet_hours(local_now, self.settings.quiet_hours_start, self.settings.quiet_hours_end) and level != "high":
            return False
        return True

    def recent_summary(self, hours: int = 24, limit: int = 10) -> list[dict]:
        since = (utcnow() - timedelta(hours=hours)).isoformat()
        rows = self.session.execute(
            select(Notification).where(Notification.created_at >= since).order_by(Notification.created_at.desc()).limit(limit)
        ).scalars()
        return [{"title": r.title, "level": r.level, "status": r.status, "created_at": r.created_at} for r in rows]

    def last_notification_at(self, dedupe_prefix: str | None = None) -> datetime | None:
        stmt = select(func.max(Notification.created_at))
        if dedupe_prefix:
            stmt = stmt.where(Notification.dedupe_key.like(f"{dedupe_prefix}%"))
        value = self.session.execute(stmt).scalar_one()
        return parse_iso(value) if value else None
