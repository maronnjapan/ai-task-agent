from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_ctx, get_session
from app.context import AppContext
from app.schemas.chats import InstructionOut, InstructionRequest
from app.schemas.common import Message
from app.schemas.execution import AgentRunOut, ManagerStatusOut
from app.schemas.notifications import ScheduledActionOut
from app.services.execution_service import ExecutionService
from app.utils import loads

router = APIRouter(prefix="/api/manager", tags=["manager"])


def _orchestrator(ctx: AppContext):
    if ctx.orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator is not running")
    return ctx.orchestrator


@router.post("/instruct", response_model=InstructionOut)
async def instruct(data: InstructionRequest, ctx: AppContext = Depends(get_ctx)):
    orchestrator = _orchestrator(ctx)
    try:
        result = await orchestrator.run_instruction(data.instruction, data.task_ids)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Manager AI failed: {exc}") from exc
    changes = []
    for key, ids in (
        ("plan", result.plan_ids),
        ("task_created", result.created_task_ids),
        ("task_updated", result.updated_task_ids),
        ("decision", result.decision_ids),
        ("notification", result.notification_ids),
        ("scheduled", result.scheduled_ids),
    ):
        changes.extend({"type": key, "id": i} for i in ids)
    return InstructionOut(
        run_id=orchestrator.status.current_run_id or "",
        status="succeeded",
        response=result.text,
        changes=changes,
    )


@router.post("/run", response_model=Message)
def run_now(ctx: AppContext = Depends(get_ctx)):
    orchestrator = _orchestrator(ctx)
    if orchestrator.paused:
        raise HTTPException(status_code=409, detail="Manager is paused")
    orchestrator.trigger("manual_run", {"source": "api"})
    return Message(message="Manager run queued")


@router.get("/status", response_model=ManagerStatusOut)
def status(ctx: AppContext = Depends(get_ctx)):
    if ctx.orchestrator is None:
        return ManagerStatusOut(state="disabled", llm_ready=False, llm_issue="orchestrator disabled")
    return ManagerStatusOut(**ctx.orchestrator.status_dict())


@router.post("/pause", response_model=ManagerStatusOut)
def pause(ctx: AppContext = Depends(get_ctx)):
    _orchestrator(ctx).pause()
    return ManagerStatusOut(**ctx.orchestrator.status_dict())


@router.post("/resume", response_model=ManagerStatusOut)
def resume(ctx: AppContext = Depends(get_ctx)):
    _orchestrator(ctx).resume()
    return ManagerStatusOut(**ctx.orchestrator.status_dict())


@router.get("/runs", response_model=list[AgentRunOut])
def runs(
    agent_type: str | None = None,
    plan_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = 0,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    rows, _ = ExecutionService(session, ctx.broker).list_runs(
        plan_id=plan_id, agent_type=agent_type, limit=limit, offset=offset
    )
    return [AgentRunOut.model_validate(r) for r in rows]


@router.get("/schedule", response_model=list[ScheduledActionOut])
def schedule(limit: int = Query(default=50, ge=1, le=500), session: Session = Depends(get_session)):
    from app.orchestrator.scheduler import SchedulerService

    return [
        ScheduledActionOut(
            id=a.id,
            task_id=a.task_id,
            execution_plan_id=a.execution_plan_id,
            action_type=a.action_type,
            payload=loads(a.payload, None),
            scheduled_at=a.scheduled_at,
            status=a.status,
            created_at=a.created_at,
            executed_at=a.executed_at,
        )
        for a in SchedulerService(session).list(limit=limit)
    ]


@router.delete("/schedule/{action_id}", response_model=Message)
def cancel_schedule(action_id: str, session: Session = Depends(get_session)):
    from app.orchestrator.scheduler import SchedulerService

    if not SchedulerService(session).cancel(action_id):
        raise HTTPException(status_code=404, detail="Scheduled action not found or not pending")
    return Message(message="cancelled")
