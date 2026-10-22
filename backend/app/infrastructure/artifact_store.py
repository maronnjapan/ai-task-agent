"""File storage for Markdown artifacts with path containment checks (SPEC 16, 27.1)."""

from __future__ import annotations

import re
from pathlib import Path

_SLUG = re.compile(r"[^A-Za-z0-9぀-ヿ㐀-鿿\-_]+")


def slugify(title: str, fallback: str = "artifact") -> str:
    slug = _SLUG.sub("-", title.strip()).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug or fallback)[:60]


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative_path: str) -> Path:
        path = (self.root / relative_path).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError("Artifact path escapes the artifacts directory")
        return path

    def directory_for(self, task_id: str | None, plan_id: str | None = None) -> str:
        if task_id:
            return f"task-{task_id[:8]}"
        if plan_id:
            return f"plan-{plan_id[:8]}"
        return "misc"

    def version_path(self, directory: str, slug: str, version: int, extension: str = ".md") -> str:
        return f"{directory}/{slug}-v{version}{extension}"

    def write(self, relative_path: str, content: str) -> Path:
        path = self.resolve(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def read(self, relative_path: str) -> str:
        path = self.resolve(relative_path)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def exists(self, relative_path: str) -> bool:
        try:
            return self.resolve(relative_path).exists()
        except ValueError:
            return False

    def delete(self, relative_path: str) -> None:
        path = self.resolve(relative_path)
        if path.exists():
            path.unlink()
