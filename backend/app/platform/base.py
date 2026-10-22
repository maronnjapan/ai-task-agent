from __future__ import annotations

import logging
import os
import subprocess
import sys
import webbrowser
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess]


def default_runner(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=False)


@dataclass
class PlatformInfo:
    name: str  # macos | windows | linux | wsl
    system: str
    release: str
    python: str
    data_directory: str
    config_directory: str
    autostart_supported: bool
    autostart_method: str
    notification_method: str
    details: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class AutostartSpec:
    """What to run at login: the command that starts the backend."""

    label: str
    command: list[str]
    working_directory: Path
    log_directory: Path
    environment: dict[str, str] = field(default_factory=dict)


class PlatformAdapter(ABC):
    name = "base"
    autostart_method = "none"
    notification_method = "in_app"

    def __init__(self, runner: CommandRunner | None = None, home: Path | None = None, env: dict[str, str] | None = None):
        self._run = runner or default_runner
        self._home = home or Path.home()
        self._env = env if env is not None else dict(os.environ)

    # --- directories -------------------------------------------------
    @abstractmethod
    def get_data_directory(self) -> Path: ...

    def get_config_directory(self) -> Path:
        return self.get_data_directory() / "config"

    # --- desktop integration ----------------------------------------
    def open_browser(self, url: str) -> bool:
        try:
            return webbrowser.open(url)
        except Exception:  # pragma: no cover - environment specific
            log.warning("Could not open browser for %s", url)
            return False

    @abstractmethod
    def open_file(self, path: Path) -> bool: ...

    @abstractmethod
    def show_notification(self, title: str, message: str) -> bool: ...

    # --- autostart --------------------------------------------------
    @abstractmethod
    def install_autostart(self, spec: AutostartSpec) -> str: ...

    @abstractmethod
    def remove_autostart(self, label: str) -> bool: ...

    @abstractmethod
    def is_autostart_installed(self, label: str) -> bool: ...

    # --- info -------------------------------------------------------
    def get_platform_info(self) -> PlatformInfo:
        import platform as _platform

        return PlatformInfo(
            name=self.name,
            system=_platform.system(),
            release=_platform.release(),
            python=sys.version.split()[0],
            data_directory=str(self.get_data_directory()),
            config_directory=str(self.get_config_directory()),
            autostart_supported=self.autostart_method != "none",
            autostart_method=self.autostart_method,
            notification_method=self.notification_method,
            details=self.extra_info(),
        )

    def extra_info(self) -> dict[str, str]:
        return {}

    # --- helpers ----------------------------------------------------
    def _which(self, binary: str) -> str | None:
        import shutil

        return shutil.which(binary)
