"""Markdown artifacts: storage, versions, diff, approval (SPEC 16, 22.4)."""

from __future__ import annotations

import difflib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.artifact_store import ArtifactStore, slugify
from app.infrastructure.events import EventBroker
from app.models import ArtifactSource, ArtifactTaskLink, ArtifactVersion, Task, TaskArtifact
from app.models.enums import Actor, ArtifactStatus
from app.services.audit_service import AuditService
from app.services.errors import NotFoundError, ValidationError
from app.utils import now_iso


class ArtifactService:
    def __init__(self, session: Session, store: ArtifactStore, broker: EventBroker | None = None):
        self.session = session
        self.store = store
        self.broker = broker
        self.audit = AuditService(session)

    # --- queries ------------------------------------------------------
    def get(self, artifact_id: str) -> TaskArtifact:
        artifact = self.session.get(TaskArtifact, artifact_id)
        if artifact is None:
            raise NotFoundError("Artifact not found")
        return artifact

    def list_for_task(self, task_id: str) -> list[TaskArtifact]:
        linked = select(ArtifactTaskLink.artifact_id).where(ArtifactTaskLink.task_id == task_id)
        stmt = (
            select(TaskArtifact)
            .where((TaskArtifact.task_id == task_id) | (TaskArtifact.id.in_(linked)))
            .order_by(TaskArtifact.updated_at.desc())
        )
        return list(self.session.execute(stmt).scalars())

    def list_for_plan(self, plan_id: str) -> list[TaskArtifact]:
        return list(
            self.session.execute(
                select(TaskArtifact)
                .where(TaskArtifact.execution_plan_id == plan_id)
                .order_by(TaskArtifact.created_at)
            ).scalars()
        )

    def list(self, status: str | None = None, limit: int = 100, offset: int = 0) -> list[TaskArtifact]:
        stmt = select(TaskArtifact)
        if status:
            stmt = stmt.where(TaskArtifact.status == status)
        return list(
            self.session.execute(
                stmt.order_by(TaskArtifact.updated_at.desc()).limit(limit).offset(offset)
            ).scalars()
        )

    def linked_task_ids(self, artifact: TaskArtifact) -> list[str]:
        ids = [link.task_id for link in artifact.task_links]
        if artifact.task_id and artifact.task_id not in ids:
            ids.insert(0, artifact.task_id)
        return ids

    def absolute_path(self, artifact: TaskArtifact) -> str:
        return str(self.store.resolve(artifact.file_path))

    # --- content ------------------------------------------------------
    def read_content(self, artifact_id: str, version: int | None = None) -> str:
        artifact = self.get(artifact_id)
        if version is None or version == artifact.version:
            return self.store.read(artifact.file_path)
        row = self._version(artifact, version)
        return self.store.read(row.file_path)

    def _version(self, artifact: TaskArtifact, version: int) -> ArtifactVersion:
        row = self.session.execute(
            select(ArtifactVersion).where(
                ArtifactVersion.artifact_id == artifact.id, ArtifactVersion.version == version
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Artifact version not found")
        return row

    # --- mutations ----------------------------------------------------
    def create(
        self,
        title: str,
        content: str,
        task_id: str | None,
        work_item_id: str | None = None,
        execution_plan_id: str | None = None,
        related_task_ids: list[str] | None = None,
        sources: list[dict] | None = None,
        actor: str = Actor.AI,
        artifact_type: str = "markdown",
    ) -> TaskArtifact:
        title = title.strip()
        if not title:
            raise ValidationError("Artifact title is required")
        if task_id and self.session.get(Task, task_id) is None:
            raise NotFoundError("Task not found")
        directory = self.store.directory_for(task_id, execution_plan_id)
        slug = slugify(title)
        # avoid collisions in the same directory
        existing = {
            a.file_path.split("/")[-1].rsplit("-v", 1)[0]
            for a in self.session.execute(
                select(TaskArtifact).where(TaskArtifact.file_path.like(f"{directory}/%"))
            ).scalars()
        }
        base = slug
        counter = 2
        while slug in existing:
            slug = f"{base}-{counter}"
            counter += 1
        relative = self.store.version_path(directory, slug, 1)
        self.store.write(relative, content)
        artifact = TaskArtifact(
            task_id=task_id,
            work_item_id=work_item_id,
            execution_plan_id=execution_plan_id,
            title=title,
            file_path=relative,
            artifact_type=artifact_type,
            version=1,
            status=ArtifactStatus.DRAFT,
        )
        self.session.add(artifact)
        self.session.flush()
        self.session.add(
            ArtifactVersion(
                artifact_id=artifact.id, version=1, file_path=relative, created_by=actor, change_note="初版"
            )
        )
        for tid in related_task_ids or []:
            if tid and tid != task_id and self.session.get(Task, tid) is not None:
                self.session.add(ArtifactTaskLink(artifact_id=artifact.id, task_id=tid))
        self.add_sources(artifact, sources or [])
        self.session.flush()
        self.audit.record(
            "artifact.created", "artifact", artifact.id, actor, {"title": title, "task_id": task_id}
        )
        self._publish("artifact.created", artifact)
        return artifact

    def update_content(
        self,
        artifact_id: str,
        content: str,
        change_note: str | None = None,
        actor: str = Actor.USER,
        sources: list[dict] | None = None,
    ) -> TaskArtifact:
        artifact = self.get(artifact_id)
        current = self.store.read(artifact.file_path)
        if current == content and not sources:
            return artifact
        new_version = artifact.version + 1
        directory, filename = artifact.file_path.rsplit("/", 1)
        slug = filename.rsplit("-v", 1)[0]
        relative = self.store.version_path(directory, slug, new_version)
        self.store.write(relative, content)
        artifact.version = new_version
        artifact.file_path = relative
        artifact.updated_at = now_iso()
        if actor == Actor.AI and artifact.status in (
            ArtifactStatus.APPROVED,
            ArtifactStatus.REVISION_REQUESTED,
        ):
            artifact.status = ArtifactStatus.DRAFT
        self.session.add(
            ArtifactVersion(
                artifact_id=artifact.id,
                version=new_version,
                file_path=relative,
                created_by=actor,
                change_note=change_note,
            )
        )
        if sources:
            self.add_sources(artifact, sources)
        self.session.flush()
        self.audit.record(
            "artifact.updated", "artifact", artifact.id, actor, {"version": new_version, "note": change_note}
        )
        self._publish("artifact.updated", artifact)
        return artifact

    def restore(self, artifact_id: str, version: int, actor: str = Actor.USER) -> TaskArtifact:
        content = self.read_content(artifact_id, version)
        return self.update_content(
            artifact_id, content, change_note=f"バージョン{version}を復元", actor=actor
        )

    def versions(self, artifact_id: str) -> list[ArtifactVersion]:
        artifact = self.get(artifact_id)
        return list(sorted(artifact.versions, key=lambda v: v.version))

    def diff(self, artifact_id: str, from_version: int, to_version: int | None = None) -> dict:
        artifact = self.get(artifact_id)
        to_version = to_version or artifact.version
        old = self.read_content(artifact_id, from_version).splitlines()
        new = self.read_content(artifact_id, to_version).splitlines()
        unified = "\n".join(
            difflib.unified_diff(old, new, fromfile=f"v{from_version}", tofile=f"v{to_version}", lineterm="")
        )
        lines: list[dict] = []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new).get_opcodes():
            if tag == "equal":
                lines.extend({"type": "context", "text": t} for t in old[i1:i2])
            else:
                lines.extend({"type": "removed", "text": t} for t in old[i1:i2])
                lines.extend({"type": "added", "text": t} for t in new[j1:j2])
        return {"from_version": from_version, "to_version": to_version, "unified": unified, "lines": lines}

    def set_status(self, artifact_id: str, status: str, actor: str = Actor.SYSTEM) -> TaskArtifact:
        artifact = self.get(artifact_id)
        artifact.status = str(ArtifactStatus(status))
        artifact.updated_at = now_iso()
        self.session.flush()
        self.audit.record("artifact.status", "artifact", artifact.id, actor, {"status": status})
        self._publish("artifact.updated", artifact)
        return artifact

    def approve(self, artifact_id: str, actor: str = Actor.USER) -> TaskArtifact:
        return self.set_status(artifact_id, ArtifactStatus.APPROVED, actor)

    def request_revision(self, artifact_id: str, instructions: str, actor: str = Actor.USER) -> TaskArtifact:
        artifact = self.set_status(artifact_id, ArtifactStatus.REVISION_REQUESTED, actor)
        from app.models import TaskContext

        for tid in self.linked_task_ids(artifact):
            self.session.add(
                TaskContext(
                    task_id=tid,
                    context=f"成果物「{artifact.title}」への修正依頼: {instructions}",
                    source="user_revision",
                    status="open",
                )
            )
        self.session.flush()
        return artifact

    def add_sources(self, artifact: TaskArtifact, sources: list[dict]) -> None:
        for src in sources:
            if not isinstance(src, dict):
                continue
            reference = str(src.get("reference") or src.get("url") or src.get("path") or "").strip()
            if not reference:
                continue
            self.session.add(
                ArtifactSource(
                    artifact_id=artifact.id,
                    title=str(src.get("title") or reference)[:300],
                    reference=reference,
                    source_type=str(src.get("source_type") or src.get("type") or "web"),
                    note=src.get("note"),
                )
            )

    def link_task(self, artifact_id: str, task_id: str) -> None:
        artifact = self.get(artifact_id)
        if task_id == artifact.task_id or any(link.task_id == task_id for link in artifact.task_links):
            return
        if self.session.get(Task, task_id) is None:
            raise NotFoundError("Task not found")
        self.session.add(ArtifactTaskLink(artifact_id=artifact_id, task_id=task_id))
        self.session.flush()

    def _publish(self, event_type: str, artifact: TaskArtifact) -> None:
        if self.broker is not None:
            self.broker.publish(
                event_type,
                {
                    "artifact_id": artifact.id,
                    "task_id": artifact.task_id,
                    "status": artifact.status,
                    "version": artifact.version,
                },
            )
