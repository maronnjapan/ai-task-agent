from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_ctx, get_session
from app.context import AppContext
from app.schemas.common import Message
from app.schemas.notifications import (
    ApprovalDecision,
    ApprovalOut,
    AuditEventOut,
    NotificationMarkRead,
    NotificationOut,
)
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.services.settings_service import SettingsService
from app.utils import loads

router = APIRouter(tags=["notifications"])


@router.get("/api/notifications", response_model=dict)
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = 0,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    service = NotificationService(
        session, SettingsService(session, ctx.settings).get_notifications(), ctx.platform, ctx.broker
    )
    rows, total = service.list(unread_only=unread_only, limit=limit, offset=offset)
    return {
        "items": [NotificationOut.model_validate(r).model_dump() for r in rows],
        "total": total,
        "unread": service.unread_count(),
    }


@router.post("/api/notifications/read", response_model=Message)
def mark_read(
    data: NotificationMarkRead | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    service = NotificationService(
        session, SettingsService(session, ctx.settings).get_notifications(), ctx.platform, ctx.broker
    )
    count = service.mark_read(data.ids if data else None)
    return Message(message=f"{count} notifications marked as read", data={"count": count})


@router.get("/api/approvals", response_model=list[ApprovalOut])
def list_approvals(
    status: str | None = "pending",
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    rows = ApprovalService(session, ctx.broker).list(status=status or None)
    return [
        ApprovalOut(
            id=r.id,
            kind=r.kind,
            connection_id=r.connection_id,
            tool_name=r.tool_name,
            arguments=loads(r.arguments, {}),
            task_id=r.task_id,
            work_item_id=r.work_item_id,
            reason=r.reason,
            status=r.status,
            result=r.result,
            created_at=r.created_at,
            resolved_at=r.resolved_at,
        )
        for r in rows
    ]


@router.post("/api/approvals/{approval_id}", response_model=ApprovalOut)
def resolve_approval(
    approval_id: str,
    data: ApprovalDecision,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    row = ApprovalService(session, ctx.broker).resolve(approval_id, data.approve, data.comment, actor="user")
    session.commit()
    if ctx.orchestrator is not None:
        ctx.orchestrator.trigger("approval_resolved", {"approval_id": row.id, "status": row.status})
    return ApprovalOut(
        id=row.id,
        kind=row.kind,
        connection_id=row.connection_id,
        tool_name=row.tool_name,
        arguments=loads(row.arguments, {}),
        task_id=row.task_id,
        work_item_id=row.work_item_id,
        reason=row.reason,
        status=row.status,
        result=row.result,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


@router.get("/api/audit", response_model=dict)
def list_audit(
    entity_type: str | None = None,
    entity_id: str | None = None,
    event_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = 0,
    session: Session = Depends(get_session),
):
    rows, total = AuditService(session).list(
        limit=limit, offset=offset, entity_type=entity_type, entity_id=entity_id, event_type=event_type
    )
    return {
        "items": [
            AuditEventOut(
                id=r.id,
                event_type=r.event_type,
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                actor=r.actor,
                details=loads(r.details, None),
                created_at=r.created_at,
            ).model_dump()
            for r in rows
        ],
        "total": total,
    }
