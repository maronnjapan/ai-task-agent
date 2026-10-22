"""Backup and restore (SPEC 24.4 / 24.5) using the SQLite online backup API."""

from __future__ import annotations

import json
import shutil
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.infrastructure.paths import DataPaths
from app.utils import now_iso

MANIFEST = "manifest.json"


@dataclass
class BackupInfo:
    path: Path
    size_bytes: int
    created_at: str
    includes: list[str]


class BackupService:
    def __init__(self, paths: DataPaths, version: str = "0"):
        self.paths = paths
        self.version = version

    def _snapshot_database(self, target: Path) -> None:
        source = sqlite3.connect(str(self.paths.database))
        try:
            dest = sqlite3.connect(str(target))
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()

    def create(self, directory: Path | None = None, label: str | None = None) -> BackupInfo:
        directory = Path(directory) if directory else self.paths.backups
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"aiwm-backup-{stamp}" + (f"-{label}" if label else "") + ".zip"
        target = directory / name
        includes: list[str] = []
        staging = directory / f".staging-{stamp}"
        staging.mkdir(parents=True, exist_ok=True)
        try:
            db_copy = staging / "app.db"
            if self.paths.database.exists():
                self._snapshot_database(db_copy)
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                if db_copy.exists():
                    zf.write(db_copy, "data/app.db")
                    includes.append("database")
                if self.paths.artifacts.exists():
                    for file in sorted(self.paths.artifacts.rglob("*")):
                        if file.is_file():
                            zf.write(file, f"artifacts/{file.relative_to(self.paths.artifacts).as_posix()}")
                    includes.append("artifacts")
                if self.paths.config.exists():
                    for file in sorted(self.paths.config.rglob("*")):
                        if file.is_file():
                            zf.write(file, f"config/{file.relative_to(self.paths.config).as_posix()}")
                    includes.append("config")
                manifest = {"created_at": now_iso(), "app_version": self.version, "includes": includes}
                zf.writestr(MANIFEST, json.dumps(manifest, indent=2))
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return BackupInfo(path=target, size_bytes=target.stat().st_size, created_at=now_iso(), includes=includes)

    def list(self, directory: Path | None = None) -> list[BackupInfo]:
        directory = Path(directory) if directory else self.paths.backups
        if not directory.exists():
            return []
        result = []
        for file in sorted(directory.glob("aiwm-backup-*.zip"), reverse=True):
            includes: list[str] = []
            created = datetime.fromtimestamp(file.stat().st_mtime).astimezone().isoformat()
            try:
                with zipfile.ZipFile(file) as zf:
                    if MANIFEST in zf.namelist():
                        manifest = json.loads(zf.read(MANIFEST))
                        includes = manifest.get("includes", [])
                        created = manifest.get("created_at", created)
            except zipfile.BadZipFile:
                continue
            result.append(BackupInfo(path=file, size_bytes=file.stat().st_size, created_at=created, includes=includes))
        return result

    def prune(self, keep_last: int, directory: Path | None = None) -> int:
        backups = self.list(directory)
        removed = 0
        for info in backups[keep_last:]:
            info.path.unlink(missing_ok=True)
            removed += 1
        return removed

    def restore(self, archive: Path) -> BackupInfo:
        """Restore from ``archive``. The current data is backed up first (SPEC 24.5)."""
        archive = Path(archive)
        if not archive.exists():
            raise FileNotFoundError(str(archive))
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            if "data/app.db" not in names:
                raise ValueError("Archive does not contain data/app.db")
            safety = self.create(label="pre-restore")
            # database
            self.paths.data.mkdir(parents=True, exist_ok=True)
            for suffix in ("", "-wal", "-shm"):
                stale = Path(str(self.paths.database) + suffix)
                if stale.exists():
                    stale.unlink()
            with zf.open("data/app.db") as src, open(self.paths.database, "wb") as dst:
                shutil.copyfileobj(src, dst)
            # artifacts
            if any(n.startswith("artifacts/") for n in names):
                if self.paths.artifacts.exists():
                    shutil.rmtree(self.paths.artifacts)
                self.paths.artifacts.mkdir(parents=True, exist_ok=True)
                for name in names:
                    if name.startswith("artifacts/") and not name.endswith("/"):
                        target = (self.paths.artifacts / name[len("artifacts/") :]).resolve()
                        if self.paths.artifacts.resolve() not in target.parents:
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(name) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
            # config
            for name in names:
                if name.startswith("config/") and not name.endswith("/"):
                    target = (self.paths.config / name[len("config/") :]).resolve()
                    if self.paths.config.resolve() not in target.parents:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        return safety
