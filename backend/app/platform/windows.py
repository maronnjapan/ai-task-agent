"""Windows adapter: %LOCALAPPDATA%\\AIWorkManager, Task Scheduler, toast notifications."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.platform.base import AutostartSpec, PlatformAdapter


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class WindowsPlatformAdapter(PlatformAdapter):
    name = "windows"
    autostart_method = "task_scheduler"
    notification_method = "windows_toast"

    def get_data_directory(self) -> Path:
        local = self._env.get("LOCALAPPDATA")
        base = Path(local) if local else self._home / "AppData" / "Local"
        return base / "AIWorkManager"

    def open_file(self, path: Path) -> bool:
        if hasattr(os, "startfile"):  # pragma: no cover - Windows only
            try:
                os.startfile(str(path))  # type: ignore[attr-defined]
                return True
            except OSError:
                return False
        result = self._run(["cmd.exe", "/c", "start", "", str(path)])
        return result.returncode == 0

    def toast_script(self, title: str, message: str) -> str:
        return (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null;"
            f"$title = {_ps_quote(title)}; $msg = {_ps_quote(message)};"
            "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument;"
            "$xml.LoadXml(\"<toast><visual><binding template='ToastGeneric'><text>$([System.Security.SecurityElement]::Escape($title))</text><text>$([System.Security.SecurityElement]::Escape($msg))</text></binding></visual></toast>\");"
            "$toast = New-Object Windows.UI.Notifications.ToastNotification $xml;"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('AI Work Manager').Show($toast);"
        )

    def show_notification(self, title: str, message: str) -> bool:
        result = self._run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", self.toast_script(title, message)]
        )
        return result.returncode == 0

    def task_name(self, label: str) -> str:
        return label.replace(".", "_")

    def wrapper_path(self, spec: AutostartSpec) -> Path:
        return spec.log_directory.parent / "autostart.cmd"

    def render_wrapper(self, spec: AutostartSpec) -> str:
        """Task Scheduler runs a bare command; the wrapper restores cwd, environment and logging."""
        lines = ["@echo off", f'cd /d "{spec.working_directory}"']
        for key, value in spec.environment.items():
            lines.append(f"set {key}={value}")
        command = subprocess.list2cmdline(spec.command)
        log_file = spec.log_directory / "autostart.log"
        lines.append(f'{command} >> "{log_file}" 2>&1')
        return "\r\n".join(lines) + "\r\n"

    def install_autostart(self, spec: AutostartSpec) -> str:
        spec.log_directory.mkdir(parents=True, exist_ok=True)
        wrapper = self.wrapper_path(spec)
        wrapper.write_text(self.render_wrapper(spec), encoding="utf-8")
        name = self.task_name(spec.label)
        result = self._run(
            [
                "schtasks.exe",
                "/Create",
                "/F",
                "/SC",
                "ONLOGON",
                "/TN",
                name,
                "/TR",
                f'"{wrapper}"',
            ]
        )
        if result.returncode != 0:
            raise RuntimeError(f"schtasks failed: {(result.stderr or result.stdout or '').strip()}")
        return name

    def remove_autostart(self, label: str) -> bool:
        result = self._run(["schtasks.exe", "/Delete", "/F", "/TN", self.task_name(label)])
        return result.returncode == 0

    def is_autostart_installed(self, label: str) -> bool:
        result = self._run(["schtasks.exe", "/Query", "/TN", self.task_name(label)])
        return result.returncode == 0
