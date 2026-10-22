from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.schemas.common import Message
from app.schemas.memories import MemoryCreate, MemoryOut, MemoryUpdate, UserStateOut, UserStateUpdate
from app.services.memory_service import MemoryService
from app.services.user_state_service import UserStateService

router = APIRouter(tags=["memories"])


@router.get("/api/memories", response_model=list[MemoryOut])
def list_memories(scope: str | None = None, task_id: str | None = None, category_id: str | None = None, kind: str | None = None, q: str | None = None, limit: int = Query(default=100, ge=1, le=1000), offset: int = 0, session: Session = Depends(get_session)):
    return [MemoryOut.model_validate(m) for m in MemoryService(session).list(scope=scope, task_id=task_id, category_id=category_id, kind=kind, query=q, limit=limit, offset=offset)]


@router.post("/api/memories", response_model=MemoryOut, status_code=201)
def create_memory(data: MemoryCreate, session: Session = Depends(get_session)):
    return MemoryOut.model_validate(MemoryService(session).create(data, actor="user"))


@router.patch("/api/memories/{memory_id}", response_model=MemoryOut)
def update_memory(memory_id: str, data: MemoryUpdate, session: Session = Depends(get_session)):
    return MemoryOut.model_validate(MemoryService(session).update(memory_id, data, actor="user"))


@router.delete("/api/memories/{memory_id}", response_model=Message)
def delete_memory(memory_id: str, session: Session = Depends(get_session)):
    MemoryService(session).delete(memory_id, actor="user")
    return Message(message="deleted")


@router.get("/api/user-state", response_model=UserStateOut)
def get_user_state(session: Session = Depends(get_session)):
    service = UserStateService(session)
    state = service.get()
    return UserStateOut(condition=state.condition, source=state.source, expires_at=state.expires_at, updated_at=state.updated_at, active=service.is_active(state))


@router.put("/api/user-state", response_model=UserStateOut)
def set_user_state(data: UserStateUpdate, session: Session = Depends(get_session)):
    service = UserStateService(session)
    state = service.set(data.condition, source="user", expires_in_minutes=data.expires_in_minutes, actor="user") if data.condition.strip() else service.clear()
    return UserStateOut(condition=state.condition, source=state.source, expires_at=state.expires_at, updated_at=state.updated_at, active=service.is_active(state))
