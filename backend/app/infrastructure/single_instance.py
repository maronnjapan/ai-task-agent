"""Single instance lock (SPEC 6.3): refuse to start a second backend on the same data directory."""

from __future__ import annotations

import os
from pathlib import Path

LOCK_OFFSET = 4096  # Windows byte-range lock lives past the pid text so reads of the pid never conflict


class AlreadyRunningError(RuntimeError):
    pass


class InstanceLock:
    def __init__(self, path: Path):
        self.path = path
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        handle = os.fdopen(fd, "r+")
        try:
            if os.name == "nt":  # pragma: no cover - Windows only
                import msvcrt

                handle.seek(LOCK_OFFSET)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise AlreadyRunningError(f"Another instance already holds {self.path}") from exc
        handle.seek(0)
        handle.write(str(os.getpid()).ljust(32))
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            if os.name == "nt":  # pragma: no cover
                import msvcrt

                handle.seek(LOCK_OFFSET)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None
            try:
                self.path.unlink()
            except OSError:
                pass

    @property
    def held(self) -> bool:
        return self._handle is not None

    def __enter__(self) -> InstanceLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()
