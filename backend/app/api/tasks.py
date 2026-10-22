from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_ctx, get_session
from app.api.serializers import artifact_out, plan_out, task_out
from app.context import AppContext
from app.infrastructure.artifact_store import ArtifactStore
from app.schemas.artifacts import ArtifactOut
from app.schemas.chats import DecisionCreate, DecisionOut
from app.schemas.execution import AgentRunOut, ExecutionPlanOut
from app.schemas.tasks import (
    ApproveRequest,
    RevisionRequest,
    TaskContextCreate,
    TaskContextOut,
    TaskCreate,
    TaskListOut,
    TaskOut,
    TaskRevert,
    TaskUpdate,
    TaskVersionOut,
)
from app.services.artifact_service import ArtifactService
from app.services.chat_service import DecisionService
from app.services.execution_service import ExecutionService
from app.services.task_service import TaskService
from app.utils import loads

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _notify_orchestrator(ctx: AppContext, event: str, payload: dict) -> None:
    if ctx.orchestrator is not None:
        ctx.orchestrator.trigger(event, payload)


@router.get("", response_model=TaskListOut)
def list_tasks(
    status: str | None = None,
    category_id: str | None = None,
    assignee: str | None = None,
    search: str | None = None,
    include_completed: bool = True,
    include_deleted: bool = False,
    order: str = "due",
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    service = TaskService(session, ctx.broker)
    tasks, total = service.list(
        status=status,
        category_id=category_id,
        assignee=assignee,
        search=search,
        include_completed=include_completed,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
        order=order,
    )
    return TaskListOut(items=[task_out(service, t) for t in tasks], total=total, limit=limit, offset=offset)


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    data: TaskCreate, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
):
    service = TaskService(session, ctx.broker)
    task = service.create(data, actor="user")
    session.commit()
    _notify_orchestrator(ctx, "task_created", {"task_id": task.id})
    return task_out(service, task)


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    service = TaskService(session, ctx.broker)
    return task_out(service, service.get(task_id, include_deleted=True))


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: str,
    data: TaskUpdate,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    service = TaskService(session, ctx.broker)
    task = service.update(task_id, data, actor="user")
    session.commit()
    _notify_orchestrator(ctx, "task_updated", {"task_id": task.id})
    return task_out(service, task)


@router.delete("/{task_id}", response_model=TaskOut)
def delete_task(task_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    service = TaskService(session, ctx.broker)
    task = service.delete(task_id, actor="user")
    return task_out(service, task)


@router.post("/{task_id}/restore", response_model=TaskOut)
def restore_task(task_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    service = TaskService(session, ctx.broker)
    return task_out(service, service.restore(task_id, actor="user"))


@router.post("/{task_id}/approve", response_model=TaskOut)
def approve_task(
    task_id: str,
    data: ApproveRequest | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    service = TaskService(session, ctx.broker)
    task = service.approve(task_id, actor="user", comment=data.comment if data else None)
    session.commit()
    _notify_orchestrator(ctx, "user_approved", {"task_id": task.id})
    return task_out(service, task)


@router.post("/{task_id}/reopen", response_model=TaskOut)
def reopen_task(
    task_id: str,
    data: ApproveRequest | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    service = TaskService(session, ctx.broker)
    task = service.reopen(task_id, actor="user", reason=data.comment if data else None)
    session.commit()
    _notify_orchestrator(ctx, "task_updated", {"task_id": task.id, "reopened": True})
    return task_out(service, task)


@router.post("/{task_id}/revision", response_model=TaskOut)
def request_revision(
    task_id: str,
    data: RevisionRequest,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    service = TaskService(session, ctx.broker)
    task = service.request_revision(task_id, data.instructions, kind=data.kind, actor="user")
    session.commit()
    if data.kind != "hold":
        _notify_orchestrator(ctx, "task_updated", {"task_id": task.id, "revision": data.kind})
    return task_out(service, task)


@router.get("/{task_id}/history", response_model=list[TaskVersionOut])
def task_history(task_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    rows = TaskService(session, ctx.broker).history(task_id)
    return [
        TaskVersionOut(
            id=v.id,
            task_id=v.task_id,
            version=v.version,
            title=v.title,
            description=v.description,
            revised_content=loads(v.revised_content, {}),
            previous_content=loads(v.previous_content, None),
            changed_by=v.changed_by,
            change_summary=v.change_summary,
            created_at=v.created_at,
        )
        for v in rows
    ]


@router.post("/{task_id}/revert", response_model=TaskOut)
def revert_task(
    task_id: str,
    data: TaskRevert,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    service = TaskService(session, ctx.broker)
    task = service.revert(task_id, data.version, actor="user")
    session.commit()
    _notify_orchestrator(ctx, "task_updated", {"task_id": task.id, "reverted": data.version})
    return task_out(service, task)


@router.get("/{task_id}/contexts", response_model=list[TaskContextOut])
def list_contexts(task_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    service = TaskService(session, ctx.broker)
    service.get(task_id, include_deleted=True)
    from sqlalchemy import select

    from app.models import TaskContext

    rows = session.execute(
        select(TaskContext).where(TaskContext.task_id == task_id).order_by(TaskContext.created_at.desc())
    ).scalars()
    return [TaskContextOut.model_validate(r) for r in rows]


@router.post("/{task_id}/contexts", response_model=TaskContextOut, status_code=201)
def add_context(
    task_id: str,
    data: TaskContextCreate,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    row = TaskService(session, ctx.broker).add_context(
        task_id, data.context, data.source or "user", actor="user"
    )
    session.commit()
    _notify_orchestrator(ctx, "task_updated", {"task_id": task_id, "context": True})
    return TaskContextOut.model_validate(row)


@router.get("/{task_id}/artifacts", response_model=list[ArtifactOut])
def task_artifacts(task_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    TaskService(session, ctx.broker).get(task_id, include_deleted=True)
    service = ArtifactService(
        session, ctx.extras.get("artifact_store") or ArtifactStore(ctx.paths.artifacts), ctx.broker
    )
    return [artifact_out(service, a) for a in service.list_for_task(task_id)]


@router.get("/{task_id}/decisions", response_model=list[DecisionOut])
def task_decisions(
    task_id: str,
    include_history: bool = True,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    TaskService(session, ctx.broker).get(task_id, include_deleted=True)
    return [
        DecisionOut.model_validate(d)
        for d in DecisionService(session, ctx.broker).list(task_id, include_history=include_history)
    ]


@router.post("/{task_id}/decisions", response_model=DecisionOut, status_code=201)
def record_decision(
    task_id: str,
    data: DecisionCreate,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    decision = DecisionService(session, ctx.broker).record(
        task_id,
        data.content,
        source_message_id=data.source_message_id,
        supersedes_id=data.supersedes_id,
        actor="user",
    )
    session.commit()
    _notify_orchestrator(ctx, "task_updated", {"task_id": task_id, "decision": decision.id})
    return DecisionOut.model_validate(decision)


@router.get("/{task_id}/plans", response_model=list[ExecutionPlanOut])
def task_plans(task_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    service = ExecutionService(session, ctx.broker)
    return [plan_out(service, p, session) for p in service.plans_for_task(task_id)]


@router.get("/{task_id}/runs", response_model=list[AgentRunOut])
def task_runs(
    task_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    rows, _ = ExecutionService(session, ctx.broker).list_runs(task_id=task_id, limit=limit)
    return [AgentRunOut.model_validate(r) for r in rows]
