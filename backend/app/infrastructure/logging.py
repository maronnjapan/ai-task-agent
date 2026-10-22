"""Logging configuration with secret redaction (SPEC 4.9 / 27.2)."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)(\s*[=:]\s*)([^\s,;'\"]{6,})"),
]

_KNOWN_SECRETS: set[str] = set()


def register_secret(value: str | None) -> None:
    """Register a secret value so it is masked whenever it appears in logs."""
    if value and len(value) >= 6:
        _KNOWN_SECRETS.add(value)


def redact(text: str) -> str:
    for secret in list(_KNOWN_SECRETS):
        if secret in text:
            text = text.replace(secret, "***")
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 3:
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)
        else:
            text = pattern.sub("***", text)
    return text


class SecretRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging(log_dir: Path | None, level: str = "INFO") -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in list(root.handlers):
        if getattr(handler, "_aiwm", False):
            root.removeHandler(handler)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(SecretRedactingFilter())
    console._aiwm = True  # type: ignore[attr-defined]
    root.addHandler(console)
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(log_dir / "app.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(SecretRedactingFilter())
        file_handler._aiwm = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)
    for noisy in ("httpx", "httpx2", "httpcore", "uvicorn.access", "alembic.runtime.plugins"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return logging.getLogger("aiwm")
