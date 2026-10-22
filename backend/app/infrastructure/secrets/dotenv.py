"""``.env`` backed Secret Provider (Windows / WSL default, SPEC 4.6-4.7)."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    # strip trailing comments for unquoted values
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def _quote(value: str) -> str:
    if value == "" or re.search(r"[\s#'\"\\$]", value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


class DotEnvSecretProvider:
    name = "dotenv"

    def __init__(self, path: Path | str, env_fallback: bool = True):
        self.path = Path(path).expanduser()
        self.env_fallback = env_fallback

    def _read_lines(self) -> list[str]:
        if not self.path.exists():
            return []
        return self.path.read_text(encoding="utf-8").splitlines()

    def _write_lines(self, lines: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.restrict_permissions()

    def restrict_permissions(self) -> None:
        if os.name != "nt":
            try:
                os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            return
        # Windows: drop inherited ACEs and grant only the current user (best effort).
        try:  # pragma: no cover - Windows only
            import subprocess

            user = os.environ.get("USERNAME")
            if user:
                subprocess.run(
                    ["icacls", str(self.path), "/inheritance:r", "/grant:r", f"{user}:F"],
                    capture_output=True,
                    check=False,
                )
        except Exception:  # noqa: BLE001
            pass

    def get_secret(self, name: str) -> str | None:
        for line in self._read_lines():
            match = _LINE.match(line)
            if match and match.group(1) == name:
                value = _unquote(match.group(2))
                if value:
                    return value
        if self.env_fallback:
            value = os.environ.get(name)
            if value:
                return value
        return None

    def set_secret(self, name: str, value: str) -> None:
        lines = self._read_lines()
        replaced = False
        for index, line in enumerate(lines):
            match = _LINE.match(line)
            if match and match.group(1) == name:
                lines[index] = f"{name}={_quote(value)}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{name}={_quote(value)}")
        self._write_lines(lines)

    def delete_secret(self, name: str) -> None:
        lines = self._read_lines()
        new_lines = []
        for line in lines:
            match = _LINE.match(line)
            if match and match.group(1) == name:
                new_lines.append(f"{name}=")
            else:
                new_lines.append(line)
        if new_lines != lines:
            self._write_lines(new_lines)
