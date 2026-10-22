from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.utils import dumps

log = logging.getLogger("aiwm.audit")


class AuditService:
    def __init__(self, session: Session):
        self.session = session

    def record(
        self,
        event_type: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        actor: str = "system",
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            actor=actor,
            details=dumps(details) if details is not None else None,
        )
        self.session.add(event)
        self.session.flush()
        log.info("%s %s/%s by %s", event_type, entity_type, entity_id, actor)
        return event

    def list(
        self,
        limit: int = 100,
        offset: int = 0,
        entity_type: str | None = None,
        entity_id: str | None = None,
        event_type: str | None = None,
    ) -> tuple[list[AuditEvent], int]:
        from sqlalchemy import func

        stmt = select(AuditEvent)
        if entity_type:
            stmt = stmt.where(AuditEvent.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(AuditEvent.entity_id == entity_id)
        if event_type:
            stmt = stmt.where(AuditEvent.event_type == event_type)
        total = self.session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        rows = self.session.execute(
            stmt.order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset)
        ).scalars().all()
        return list(rows), int(total)
