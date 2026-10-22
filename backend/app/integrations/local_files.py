"""Local file information source (SPEC 17.12) with directory containment (SPEC 27.2 #5)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from app.schemas.settings import LocalSourceSettings


@dataclass
class LocalFileHit:
    path: str
    line: int
    snippet: str


class LocalFileAccessError(PermissionError):
    pass


class LocalFileSource:
    def __init__(self, settings: LocalSourceSettings):
        self.settings = settings
        self.roots = [Path(d).expanduser().resolve() for d in settings.directories if d]
        self.extensions = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in settings.extensions}
        self.max_bytes = settings.max_file_size_kb * 1024

    def is_allowed(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        if resolved.suffix.lower() not in self.extensions:
            return False
        return any(resolved == root or root in resolved.parents for root in self.roots)

    def iter_files(self):
        for root in self.roots:
            if not root.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".venv", "venv")]
                for name in filenames:
                    path = Path(dirpath) / name
                    if path.suffix.lower() in self.extensions:
                        yield path

    def search(self, query: str, limit: int = 20, max_files: int = 5000) -> list[LocalFileHit]:
        terms = [t for t in re.split(r"\s+", query.strip()) if t]
        if not terms or not self.roots:
            return []
        lowered = [t.lower() for t in terms]
        hits: list[LocalFileHit] = []
        scanned = 0
        for path in self.iter_files():
            scanned += 1
            if scanned > max_files:
                break
            try:
                if path.stat().st_size > self.max_bytes:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            name_match = all(t in path.name.lower() for t in lowered)
            for number, line in enumerate(text.splitlines(), start=1):
                low = line.lower()
                if all(t in low for t in lowered):
                    hits.append(LocalFileHit(path=str(path), line=number, snippet=line.strip()[:300]))
                    if len(hits) >= limit:
                        return hits
            if name_match and not any(h.path == str(path) for h in hits):
                hits.append(LocalFileHit(path=str(path), line=0, snippet="(file name match)"))
                if len(hits) >= limit:
                    return hits
        return hits

    def read(self, path: str, max_chars: int = 20_000) -> str:
        target = Path(path).expanduser()
        if not self.is_allowed(target):
            raise LocalFileAccessError(f"Access to {path} is not allowed (outside configured directories or extension not permitted)")
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(path)
        if target.stat().st_size > self.max_bytes:
            raise LocalFileAccessError(f"File exceeds the configured size limit ({self.settings.max_file_size_kb} KB)")
        text = target.read_text(encoding="utf-8", errors="ignore")
        return text[:max_chars]
