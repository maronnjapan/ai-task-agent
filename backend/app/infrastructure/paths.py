"""Data directory layout (see SPEC 5.3)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def database(self) -> Path:
        return self.data / "app.db"

    @property
    def artifacts(self) -> Path:
        return self.root / "artifacts"

    @property
    def backups(self) -> Path:
        return self.root / "backups"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def settings_file(self) -> Path:
        return self.config / "settings.json"

    @property
    def lock_file(self) -> Path:
        return self.root / "aiwm.lock"

    @property
    def pid_file(self) -> Path:
        return self.root / "aiwm.pid"

    def ensure(self) -> DataPaths:
        for directory in (self.root, self.data, self.artifacts, self.backups, self.logs, self.exports, self.config):
            directory.mkdir(parents=True, exist_ok=True)
        return self


def build_paths(root: Path | str) -> DataPaths:
    return DataPaths(Path(root).expanduser().resolve())
