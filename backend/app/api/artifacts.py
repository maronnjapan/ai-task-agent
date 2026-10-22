from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_ctx, get_session
from app.api.serializers import artifact_out
from app.context import AppContext
from app.infrastructure.artifact_store import ArtifactStore
from app.schemas.artifacts import (
    ArtifactContentOut,
    ArtifactContentUpdate,
    ArtifactCreate,
    ArtifactDiffOut,
    ArtifactOut,
    ArtifactRestore,
    ArtifactVersionOut,
)
from app.schemas.common import Message
from app.schemas.tasks import RevisionRequest
from app.services.artifact_service import ArtifactService

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


def _service(session: Session, ctx: AppContext) -> ArtifactService:
    return ArtifactService(
        session, ctx.extras.get("artifact_store") or ArtifactStore(ctx.paths.artifacts), ctx.broker
    )


@router.get("", response_model=list[ArtifactOut])
def list_artifacts(
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = 0,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    service = _service(session, ctx)
    return [artifact_out(service, a) for a in service.list(status=status, limit=limit, offset=offset)]


@router.post("", response_model=ArtifactOut, status_code=201)
def create_artifact(
    data: ArtifactCreate, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
):
    service = _service(session, ctx)
    artifact = service.create(data.title, data.content, data.task_id, actor="user")
    return artifact_out(service, artifact)


@router.get("/{artifact_id}", response_model=ArtifactOut)
def get_artifact(
    artifact_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
):
    service = _service(session, ctx)
    return artifact_out(service, service.get(artifact_id))


@router.get("/{artifact_id}/content", response_model=ArtifactContentOut)
def get_content(
    artifact_id: str,
    version: int | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    service = _service(session, ctx)
    artifact = service.get(artifact_id)
    return ArtifactContentOut(
        id=artifact.id,
        version=version or artifact.version,
        content=service.read_content(artifact_id, version),
    )


@router.put("/{artifact_id}/content", response_model=ArtifactOut)
def put_content(
    artifact_id: str,
    data: ArtifactContentUpdate,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    service = _service(session, ctx)
    return artifact_out(
        service,
        service.update_content(
            artifact_id, data.content, change_note=data.change_note or "ユーザーが編集", actor="user"
        ),
    )


@router.get("/{artifact_id}/versions", response_model=list[ArtifactVersionOut])
def versions(artifact_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    return [ArtifactVersionOut.model_validate(v) for v in _service(session, ctx).versions(artifact_id)]


@router.post("/{artifact_id}/restore", response_model=ArtifactOut)
def restore(
    artifact_id: str,
    data: ArtifactRestore,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    service = _service(session, ctx)
    return artifact_out(service, service.restore(artifact_id, data.version, actor="user"))


@router.get("/{artifact_id}/diff", response_model=ArtifactDiffOut)
def diff(
    artifact_id: str,
    from_version: int = Query(alias="from"),
    to_version: int | None = Query(default=None, alias="to"),
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    return ArtifactDiffOut(**_service(session, ctx).diff(artifact_id, from_version, to_version))


@router.post("/{artifact_id}/approve", response_model=ArtifactOut)
def approve(artifact_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    service = _service(session, ctx)
    return artifact_out(service, service.approve(artifact_id, actor="user"))


@router.post("/{artifact_id}/revision", response_model=ArtifactOut)
def request_revision(
    artifact_id: str,
    data: RevisionRequest,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    service = _service(session, ctx)
    artifact = service.request_revision(artifact_id, data.instructions, actor="user")
    session.commit()
    if ctx.orchestrator is not None:
        ctx.orchestrator.trigger("task_updated", {"artifact_id": artifact.id, "revision": True})
    return artifact_out(service, artifact)


@router.get("/{artifact_id}/export")
def export_artifact(
    artifact_id: str,
    format: str = Query(default="markdown"),
    save: bool = Query(default=False, description="also write the file to the exports directory"),
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    """Export the current version (markdown | text | html, extensible via ``register_exporter``)."""
    from fastapi import HTTPException
    from fastapi.responses import Response

    from app.infrastructure.artifact_store import slugify
    from app.services.exporters import export

    service = _service(session, ctx)
    artifact = service.get(artifact_id)
    try:
        result = export(format, artifact.title, service.read_content(artifact_id))
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = f"{slugify(artifact.title)}-v{artifact.version}{result.extension}"
    if save:
        ctx.paths.exports.mkdir(parents=True, exist_ok=True)
        (ctx.paths.exports / filename).write_bytes(result.content)
    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{__import__('urllib.parse').parse.quote(filename)}"
        },
    )


@router.post("/{artifact_id}/open", response_model=Message)
def open_file(artifact_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    service = _service(session, ctx)
    artifact = service.get(artifact_id)
    from pathlib import Path

    ok = ctx.platform.open_file(Path(service.absolute_path(artifact)))
    return Message(
        ok=ok,
        message="opened" if ok else "could not open the file with the default application",
        data={"path": service.absolute_path(artifact)},
    )
