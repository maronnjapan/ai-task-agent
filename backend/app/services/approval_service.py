"""User approval requests for external-write operations (SPEC 17.14, 27.2)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.events import EventBroker
from app.models import ApprovalRequest
from app.services.audit_service import AuditService
from app.services.errors import NotFoundError, ValidationError
from app.utils import dumps, now_iso


class ApprovalService:
    def __init__(self, session: Session, broker: EventBroker | None = None):
        self.session = session
        self.broker = broker
        self.audit = AuditService(session)

    def list(self, status: str | None = "pending", limit: int = 100) -> list[ApprovalRequest]:
        stmt = select(ApprovalRequest)
        if status:
            stmt = stmt.where(ApprovalRequest.status == status)
        return list(
            self.session.execute(stmt.order_by(ApprovalRequest.created_at.desc()).limit(limit)).scalars()
        )

    def get(self, approval_id: str) -> ApprovalRequest:
        row = self.session.get(ApprovalRequest, approval_id)
        if row is None:
            raise NotFoundError("Approval request not found")
        return row

    def request(
        self,
        tool_name: str,
        arguments: dict,
        connection_id: str | None = None,
        task_id: str | None = None,
        work_item_id: str | None = None,
        reason: str | None = None,
        kind: str = "mcp_tool_call",
    ) -> ApprovalRequest:
        row = ApprovalRequest(
            kind=kind,
            connection_id=connection_id,
            tool_name=tool_name,
            arguments=dumps(arguments),
            task_id=task_id,
            work_item_id=work_item_id,
            reason=reason,
        )
        self.session.add(row)
        self.session.flush()
        self.audit.record(
            "approval.requested",
            "approval",
            row.id,
            "ai",
            {"tool": tool_name, "connection_id": connection_id},
        )
        if self.broker:
            self.broker.publish(
                "approval.requested", {"approval_id": row.id, "tool_name": tool_name, "task_id": task_id}
            )
        return row

    def resolve(
        self, approval_id: str, approve: bool, comment: str | None = None, actor: str = "user"
    ) -> ApprovalRequest:
        row = self.get(approval_id)
        if row.status != "pending":
            raise ValidationError("Approval request already resolved")
        row.status = "approved" if approve else "rejected"
        row.result = comment
        row.resolved_at = now_iso()
        self.session.flush()
        self.audit.record(
            "approval.resolved", "approval", row.id, actor, {"approved": approve, "comment": comment}
        )
        if self.broker:
            self.broker.publish(
                "approval.resolved", {"approval_id": row.id, "status": row.status, "task_id": row.task_id}
            )
        return row
