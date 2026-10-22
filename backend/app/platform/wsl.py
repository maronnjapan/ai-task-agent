"""WSL adapter: Linux behaviour plus bridges to the Windows host (browser, notifications)."""

from __future__ import annotations

from pathlib import Path

from app.platform.linux import LinuxPlatformAdapter
from app.platform.windows import WindowsPlatformAdapter


class WSLPlatformAdapter(LinuxPlatformAdapter):
    name = "wsl"
    notification_method = "windows_toast_bridge"

    def _powershell(self) -> str | None:
        for candidate in ("powershell.exe", "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"):
            if candidate.startswith("/"):
                if Path(candidate).exists():
                    return candidate
            elif self._which(candidate):
                return candidate
        return None

    def open_browser(self, url: str) -> bool:
        if self._which("wslview"):
            return self._run(["wslview", url]).returncode == 0
        powershell = self._powershell()
        if powershell:
            return self._run([powershell, "-NoProfile", "-Command", f"Start-Process '{url}'"]).returncode == 0
        if self._which("cmd.exe"):
            return self._run(["cmd.exe", "/c", "start", "", url]).returncode == 0
        return super().open_browser(url)

    def open_file(self, path: Path) -> bool:
        if self._which("wslview"):
            return self._run(["wslview", str(path)]).returncode == 0
        return super().open_file(path)

    def show_notification(self, title: str, message: str) -> bool:
        powershell = self._powershell()
        if powershell:
            script = WindowsPlatformAdapter(runner=self._run, home=self._home, env=self._env).toast_script(
                title, message
            )
            result = self._run([powershell, "-NoProfile", "-NonInteractive", "-Command", script])
            if result.returncode == 0:
                return True
        return super().show_notification(title, message)

    @property
    def autostart_method(self) -> str:  # type: ignore[override]
        return "systemd_user" if self.systemd_available() else "profile_script"

    def extra_info(self) -> dict[str, str]:
        info = super().extra_info()
        info["windows_bridge"] = "yes" if self._powershell() else "no"
        info["autostart_method"] = self.autostart_method
        return info
