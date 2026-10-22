"""macOS Keychain Secret Provider (SPEC 4.3).

The Keychain is accessed through the ``security`` command line tool so that no
native extension is required. The command runner is injectable for tests.
"""

from __future__ import annotations

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
        # ``-U`` updates an existing item instead of failing; the value is passed on
        # the command line of a *local* helper process only, never logged.
        result = self._run(
            ["security", "add-generic-password", "-s", self.service, "-a", name, "-w", value, "-U"],
            None,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Keychain write failed for {name}: {(result.stderr or '').strip()}")

    def delete_secret(self, name: str) -> None:
        self._run(["security", "delete-generic-password", "-s", self.service, "-a", name], None)
