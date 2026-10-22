"""macOS adapter: ~/.ai-work-manager, launchd autostart, osascript notifications."""

from __future__ import annotations

import plistlib
from pathlib import Path

from app.platform.base import AutostartSpec, PlatformAdapter


class MacOSPlatformAdapter(PlatformAdapter):
    name = "macos"
    autostart_method = "launchd"
    notification_method = "macos_notification"

    def get_data_directory(self) -> Path:
        return self._home / ".ai-work-manager"

    def launch_agents_dir(self) -> Path:
        return self._home / "Library" / "LaunchAgents"

    def plist_path(self, label: str) -> Path:
        return self.launch_agents_dir() / f"{label}.plist"

    def open_file(self, path: Path) -> bool:
        result = self._run(["open", str(path)])
        return result.returncode == 0

    def show_notification(self, title: str, message: str) -> bool:
        safe_title = title.replace('"', '\\"')
        safe_message = message.replace('"', '\\"')
        script = f'display notification "{safe_message}" with title "{safe_title}"'
        result = self._run(["osascript", "-e", script])
        return result.returncode == 0

    def install_autostart(self, spec: AutostartSpec) -> str:
        self.launch_agents_dir().mkdir(parents=True, exist_ok=True)
        spec.log_directory.mkdir(parents=True, exist_ok=True)
        plist = {
            "Label": spec.label,
            "ProgramArguments": spec.command,
            "WorkingDirectory": str(spec.working_directory),
            "RunAtLoad": True,
            "KeepAlive": False,
            "StandardOutPath": str(spec.log_directory / "launchd.out.log"),
            "StandardErrorPath": str(spec.log_directory / "launchd.err.log"),
        }
        if spec.environment:
            plist["EnvironmentVariables"] = dict(spec.environment)
        path = self.plist_path(spec.label)
        with open(path, "wb") as handle:
            plistlib.dump(plist, handle)
        self._run(["launchctl", "unload", str(path)])
        self._run(["launchctl", "load", str(path)])
        return str(path)

    def remove_autostart(self, label: str) -> bool:
        path = self.plist_path(label)
        if not path.exists():
            return False
        self._run(["launchctl", "unload", str(path)])
        path.unlink()
        return True

    def is_autostart_installed(self, label: str) -> bool:
        return self.plist_path(label).exists()
