from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, id_column, ts_column


class TaskArtifact(Base):
    __tablename__ = "task_artifacts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','review_pending','approved','revision_requested')", name="ck_task_artifacts_status"
        ),
        Index("ix_task_artifacts_task", "task_id"),
    )

    id: Mapped[str] = id_column()
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    work_item_id: Mapped[str | None] = mapped_column(ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True)
    execution_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_plans.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)  # relative to the artifacts directory
    artifact_type: Mapped[str] = mapped_column(String, nullable=False, default="markdown")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    created_at: Mapped[str] = ts_column()
    updated_at: Mapped[str] = ts_column()

    versions: Mapped[list[ArtifactVersion]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan", order_by="ArtifactVersion.version"
    )
    task_links: Mapped[list[ArtifactTaskLink]] = relationship(back_populates="artifact", cascade="all, delete-orphan")
    sources: Mapped[list[ArtifactSource]] = relationship(back_populates="artifact", cascade="all, delete-orphan")


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (UniqueConstraint("artifact_id", "version", name="uq_artifact_versions_version"),)

    id: Mapped[str] = id_column()
    artifact_id: Mapped[str] = mapped_column(ForeignKey("task_artifacts.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False, default="ai")
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = ts_column()

    artifact: Mapped[TaskArtifact] = relationship(back_populates="versions")


class ArtifactTaskLink(Base):
    __tablename__ = "artifact_task_links"

    artifact_id: Mapped[str] = mapped_column(ForeignKey("task_artifacts.id", ondelete="CASCADE"), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)

    artifact: Mapped[TaskArtifact] = relationship(back_populates="task_links")


class ArtifactSource(Base):
    __tablename__ = "artifact_sources"

    id: Mapped[str] = id_column()
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("task_artifacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    reference: Mapped[str] = mapped_column(Text, nullable=False)  # URL, file path, Slack permalink, ...
    source_type: Mapped[str] = mapped_column(String, nullable=False, default="web")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = ts_column()

    artifact: Mapped[TaskArtifact] = relationship(back_populates="sources")
