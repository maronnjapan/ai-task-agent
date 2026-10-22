from __future__ import annotations

import os
import platform as _platform
from functools import lru_cache
from pathlib import Path

from app.platform.base import PlatformAdapter


def detect_platform_name(system: str | None = None, proc_version: str | None = None, env: dict | None = None) -> str:
    env = env if env is not None else os.environ
    override = env.get("AIWM_PLATFORM")
    if override:
        return override.lower()
    system = (system or _platform.system()).lower()
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    if proc_version is None:
        try:
            proc_version = Path("/proc/version").read_text(encoding="utf-8", errors="ignore")
        except OSError:
            proc_version = ""
    lowered = proc_version.lower()
    if "microsoft" in lowered or "wsl" in lowered or env.get("WSL_DISTRO_NAME"):
        return "wsl"
    return "linux"


def make_platform_adapter(name: str | None = None, **kwargs) -> PlatformAdapter:
    name = (name or detect_platform_name()).lower()
    if name == "macos":
        from app.platform.macos import MacOSPlatformAdapter

        return MacOSPlatformAdapter(**kwargs)
    if name == "windows":
        from app.platform.windows import WindowsPlatformAdapter

        return WindowsPlatformAdapter(**kwargs)
    if name == "wsl":
        from app.platform.wsl import WSLPlatformAdapter

        return WSLPlatformAdapter(**kwargs)
    from app.platform.linux import LinuxPlatformAdapter

    return LinuxPlatformAdapter(**kwargs)


@lru_cache
def get_platform_adapter() -> PlatformAdapter:
    return make_platform_adapter()
