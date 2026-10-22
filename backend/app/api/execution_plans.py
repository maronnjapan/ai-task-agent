from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_ctx, get_session
from app.api.serializers import plan_out, review_out, work_item_out
from app.context import AppContext
from app.schemas.execution import ExecutionPlanOut, ReviewOut, WorkItemOut
from app.services.execution_service import ExecutionService

router = APIRouter(prefix="/api/execution-plans", tags=["execution-plans"])


@router.get("", response_model=list[ExecutionPlanOut])
def list_plans(status: str | None = None, task_id: str | None = None, limit: int = Query(default=50, ge=1, le=500), offset: int = 0, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    service = ExecutionService(session, ctx.broker)
    plans, _ = service.list_plans(status=status, task_id=task_id, limit=limit, offset=offset)
    return [plan_out(service, p, session) for p in plans]


@router.get("/{plan_id}", response_model=ExecutionPlanOut)
def get_plan(plan_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    service = ExecutionService(session, ctx.broker)
    return plan_out(service, service.get_plan(plan_id), session)


@router.get("/{plan_id}/work-items", response_model=list[WorkItemOut])
def plan_work_items(plan_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    service = ExecutionService(session, ctx.broker)
    deps = service.dependencies(plan_id)
    return [work_item_out(i, deps) for i in service.list_work_items(plan_id)]


@router.get("/{plan_id}/reviews", response_model=list[ReviewOut])
def plan_reviews(plan_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    return [review_out(r) for r in ExecutionService(session, ctx.broker).list_reviews(plan_id)]
