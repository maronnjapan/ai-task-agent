from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app import __version__
from app.api.deps import get_ctx, get_session
from app.api.settings import AUTOSTART_LABEL
from app.context import AppContext
from app.infrastructure.backup import BackupService
from app.models import ChatMessage, Memory, Notification, Task, TaskArtifact
from app.schemas.system import BackupOut, BackupRequest, RestoreOut, RestoreRequest, SystemStatusOut
from app.services.audit_service import AuditService
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status", response_model=SystemStatusOut)
def status(session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    counts = {
        "tasks": int(session.execute(select(func.count(Task.id)).where(Task.is_deleted.is_(False))).scalar_one()),
        "review_pending": int(session.execute(select(func.count(Task.id)).where(Task.status == "review_pending", Task.is_deleted.is_(False))).scalar_one()),
        "artifacts": int(session.execute(select(func.count(TaskArtifact.id))).scalar_one()),
        "memories": int(session.execute(select(func.count(Memory.id))).scalar_one()),
        "messages": int(session.execute(select(func.count(ChatMessage.id))).scalar_one()),
        "unread_notifications": int(session.execute(select(func.count(Notification.id)).where(Notification.status == "unread")).scalar_one()),
    }
    manager = ctx.orchestrator.status_dict() if ctx.orchestrator else {"state": "disabled"}
    return SystemStatusOut(
        version=__version__,
        platform=ctx.platform.get_platform_info().to_dict(),
        data_directory=str(ctx.paths.root),
        database_path=str(ctx.paths.database),
        uptime_seconds=ctx.uptime_seconds,
        manager=manager,
        counts=counts,
        sse_subscribers=ctx.broker.subscriber_count,
        autostart_installed=ctx.platform.is_autostart_installed(AUTOSTART_LABEL),
        pid=os.getpid(),
        secret_backend=getattr(ctx.secret_store, "name", "unknown"),
    )


@router.post("/backup", response_model=BackupOut)
def backup(data: BackupRequest | None = None, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    settings = SettingsService(session, ctx.settings).get_backup()
    directory = (data.directory if data and data.directory else None) or settings.directory
    service = BackupService(ctx.paths, __version__)
    try:
        info = service.create(Path(directory) if directory else None, label=data.label if data else None)
        service.prune(settings.keep_last, Path(directory) if directory else None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Backup failed: {exc}") from exc
    AuditService(session).record("backup.created", "system", None, "user", {"path": str(info.path)})
    return BackupOut(path=str(info.path), size_bytes=info.size_bytes, created_at=info.created_at, includes=info.includes)


@router.get("/backups", response_model=list[BackupOut])
def list_backups(session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    settings = SettingsService(session, ctx.settings).get_backup()
    service = BackupService(ctx.paths, __version__)
    return [BackupOut(path=str(b.path), size_bytes=b.size_bytes, created_at=b.created_at, includes=b.includes) for b in service.list(Path(settings.directory) if settings.directory else None)]


@router.post("/restore", response_model=RestoreOut)
async def restore(data: RestoreRequest, ctx: AppContext = Depends(get_ctx)):
    if not data.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true; the current data will be backed up and then replaced")
    archive = Path(data.path).expanduser()
    if not archive.exists():
        raise HTTPException(status_code=404, detail="Backup file not found")
    orchestrator = ctx.orchestrator
    was_paused = orchestrator.paused if orchestrator else True
    if orchestrator and not was_paused:
        orchestrator.pause()
    service = BackupService(ctx.paths, __version__)
    try:
        ctx.db.engine.dispose()
        safety = service.restore(archive)
        ctx.db.reinitialize()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Restore failed: {exc}") from exc
    finally:
        if orchestrator and not was_paused:
            orchestrator.resume()
    with ctx.db.session() as session:
        AuditService(session).record("backup.restored", "system", None, "user", {"from": str(archive), "safety_backup": str(safety.path)})
    ctx.broker.publish("system.restored", {"from": str(archive)})
    return RestoreOut(restored_from=str(archive), safety_backup=str(safety.path), message="復元が完了しました。画面を再読み込みしてください。")


@router.get("/events")
async def events(request: Request, ctx: AppContext = Depends(get_ctx)):
    """Server-Sent Events stream (SPEC 25)."""
    token, queue = ctx.broker.subscribe()
    last_id = request.headers.get("last-event-id")

    async def generator():
        try:
            yield {"event": "hello", "data": json.dumps({"version": __version__, "manager": ctx.orchestrator.status_dict() if ctx.orchestrator else None}, ensure_ascii=False)}
            if last_id and last_id.isdigit():
                for event in ctx.broker.history(int(last_id)):
                    yield {"id": str(event.id), "event": event.type, "data": json.dumps(event.to_dict(), ensure_ascii=False)}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                yield {"id": str(event.id), "event": event.type, "data": json.dumps(event.to_dict(), ensure_ascii=False)}
        finally:
            ctx.broker.unsubscribe(token)

    return EventSourceResponse(generator())


@router.post("/open-data-dir", response_model=dict)
def open_data_dir(ctx: AppContext = Depends(get_ctx)):
    ok = ctx.platform.open_file(ctx.paths.root)
    return {"ok": ok, "path": str(ctx.paths.root)}
