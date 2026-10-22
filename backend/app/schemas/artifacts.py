from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ArtifactSourceOut(ORMModel):
    id: str
    title: str
    reference: str
    source_type: str
    note: str | None
    created_at: str


class ArtifactOut(ORMModel):
    id: str
    task_id: str | None
    work_item_id: str | None
    execution_plan_id: str | None
    title: str
    file_path: str
    absolute_path: str | None = None
    artifact_type: str
    version: int
    status: str
    created_at: str
    updated_at: str
    linked_task_ids: list[str] = Field(default_factory=list)
    sources: list[ArtifactSourceOut] = Field(default_factory=list)


class ArtifactContentOut(BaseModel):
    id: str
    version: int
    content: str


class ArtifactContentUpdate(BaseModel):
    content: str
    change_note: str | None = None


class ArtifactVersionOut(ORMModel):
    id: str
    artifact_id: str
    version: int
    file_path: str
    created_by: str
    change_note: str | None
    created_at: str


class ArtifactRestore(BaseModel):
    version: int


class ArtifactDiffOut(BaseModel):
    from_version: int
    to_version: int
    unified: str
    lines: list[dict]


class ArtifactCreate(BaseModel):
    task_id: str
    title: str = Field(min_length=1)
    content: str = ""
