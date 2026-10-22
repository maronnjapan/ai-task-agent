"""Linux adapter (also the base for WSL): ~/.ai-work-manager, systemd user service, notify-send."""

from __future__ import annotations

from pathlib import Path

from app.platform.base import AutostartSpec, PlatformAdapter


class LinuxPlatformAdapter(PlatformAdapter):
    name = "linux"
    autostart_method = "systemd_user"
    notification_method = "notify_send"

    def get_data_directory(self) -> Path:
        return self._home / ".ai-work-manager"

    def systemd_user_dir(self) -> Path:
        return self._home / ".config" / "systemd" / "user"

    def service_path(self, label: str) -> Path:
        return self.systemd_user_dir() / f"{label}.service"

    def systemd_available(self) -> bool:
        if self._which("systemctl") is None:
            return False
        result = self._run(["systemctl", "--user", "is-system-running"])
        output = (result.stdout or "").strip()
        return result.returncode == 0 or output in ("running", "degraded", "starting")

    def open_file(self, path: Path) -> bool:
        if self._which("xdg-open") is None:
            return False
        result = self._run(["xdg-open", str(path)])
        return result.returncode == 0

    def show_notification(self, title: str, message: str) -> bool:
        if self._which("notify-send") is None:
            return False
        result = self._run(["notify-send", title, message])
        return result.returncode == 0

    def render_service(self, spec: AutostartSpec) -> str:
        exec_start = " ".join(_sh_quote(part) for part in spec.command)
        env_lines = "".join(
            f"Environment={key}={_sh_quote(value)}\n" for key, value in spec.environment.items()
        )
        return (
            "[Unit]\n"
            "Description=Autonomous AI Work Manager\n"
            "After=network.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            f"WorkingDirectory={spec.working_directory}\n"
            f"ExecStart={exec_start}\n"
            f"{env_lines}"
            "Restart=on-failure\n"
            "RestartSec=10\n"
            "RestartPreventExitStatus=2\n\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )

    def install_autostart(self, spec: AutostartSpec) -> str:
        if not self.systemd_available():
            return self._install_profile_autostart(spec)
        self.systemd_user_dir().mkdir(parents=True, exist_ok=True)
        path = self.service_path(spec.label)
        path.write_text(self.render_service(spec), encoding="utf-8")
        self._run(["systemctl", "--user", "daemon-reload"])
        # ``enable`` only: the app is usually running while this is configured; a second instance
        # would exit with status 2 (lock held) and loop under Restart=on-failure.
        self._run(["systemctl", "--user", "enable", f"{spec.label}.service"])
        return str(path)

    def remove_autostart(self, label: str) -> bool:
        removed = False
        path = self.service_path(label)
        if path.exists():
            self._run(["systemctl", "--user", "disable", "--now", f"{label}.service"])
            path.unlink()
            self._run(["systemctl", "--user", "daemon-reload"])
            removed = True
        if self._remove_profile_autostart(label):
            removed = True
        return removed

    def is_autostart_installed(self, label: str) -> bool:
        return self.service_path(label).exists() or self._profile_marker(label) in self._profile_text()

    # --- fallback for environments without systemd (e.g. older WSL) ---
    def profile_path(self) -> Path:
        return self._home / ".profile"

    def _profile_marker(self, label: str) -> str:
        return f"# >>> {label} autostart >>>"

    def _profile_text(self) -> str:
        path = self.profile_path()
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _install_profile_autostart(self, spec: AutostartSpec) -> str:
        self._remove_profile_autostart(spec.label)
        marker = self._profile_marker(spec.label)
        command = " ".join(_sh_quote(part) for part in spec.command)
        block = (
            f"\n{marker}\n"
            f"if ! pgrep -f 'aiwm start' >/dev/null 2>&1; then\n"
            f"  (cd {_sh_quote(str(spec.working_directory))} && nohup {command} "
            f">> {_sh_quote(str(spec.log_directory / 'autostart.log'))} 2>&1 &)\n"
            "fi\n"
            f"# <<< {spec.label} autostart <<<\n"
        )
        path = self.profile_path()
        path.write_text(self._profile_text() + block, encoding="utf-8")
        return str(path)

    def _remove_profile_autostart(self, label: str) -> bool:
        text = self._profile_text()
        start = text.find(self._profile_marker(label))
        if start == -1:
            return False
        end_marker = f"# <<< {label} autostart <<<\n"
        end = text.find(end_marker, start)
        if end == -1:
            return False
        new_text = text[:start].rstrip("\n") + "\n" + text[end + len(end_marker) :]
        self.profile_path().write_text(new_text, encoding="utf-8")
        return True

    def extra_info(self) -> dict[str, str]:
        return {"systemd": "yes" if self.systemd_available() else "no"}


def _sh_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)
