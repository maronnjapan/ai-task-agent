"""macOS Keychain Secret Provider (SPEC 4.3).

The Keychain is accessed through the ``security`` command line tool so that no
native extension is required. Secret values are never passed as process
arguments (SPEC 4.9): writes use ``security -i`` which reads commands from
standard input, and reads take the value from standard output.
The command runner is injectable for tests.
"""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable

CommandRunner = Callable[[list[str], str | None], subprocess.CompletedProcess]


def _default_runner(args: list[str], input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, input=input_text, capture_output=True, text=True, check=False)


class MacOSKeychainSecretProvider:
    name = "keychain"

    def __init__(self, service: str = "ai-work-manager", runner: CommandRunner | None = None):
        self.service = service
        self._run = runner or _default_runner

    def get_secret(self, name: str) -> str | None:
        result = self._run(
            ["security", "find-generic-password", "-s", self.service, "-a", name, "-w"],
            None,
        )
        if result.returncode != 0:
            return None
        value = (result.stdout or "").strip()
        return value or None

    def set_secret(self, name: str, value: str) -> None:
        if "\n" in value or "\r" in value:
            raise ValueError("Secret values must not contain line breaks")
        # ``-U`` updates an existing item. The command (with the secret) is sent
        # over stdin to ``security -i`` so the value never appears in ``ps``.
        command = f"add-generic-password -s {shlex.quote(self.service)} -a {shlex.quote(name)} -U -w {shlex.quote(value)}\n"
        result = self._run(["security", "-i"], command)
        if result.returncode != 0:
            raise RuntimeError(f"Keychain write failed for {name}: {(result.stderr or '').strip()}")

    def delete_secret(self, name: str) -> None:
        self._run(["security", "delete-generic-password", "-s", self.service, "-a", name], None)
