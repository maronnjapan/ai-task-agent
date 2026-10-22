from __future__ import annotations

from pathlib import Path

from app.platform.base import AutostartSpec
from app.platform.factory import detect_platform_name, make_platform_adapter
from app.platform.linux import LinuxPlatformAdapter
from app.platform.macos import MacOSPlatformAdapter
from app.platform.windows import WindowsPlatformAdapter
from app.platform.wsl import WSLPlatformAdapter
from tests.conftest import FakeRunner


def spec(tmp_path: Path) -> AutostartSpec:
    return AutostartSpec(
        label="com.aiworkmanager.test",
        command=["/usr/bin/uv", "run", "aiwm", "start"],
        working_directory=tmp_path,
        log_directory=tmp_path / "logs",
        environment={"AIWM_ENV_FILE": str(tmp_path / ".env")},
    )


def test_platform_detection():
    assert detect_platform_name("Darwin", "", {}) == "macos"
    assert detect_platform_name("Windows", "", {}) == "windows"
    assert detect_platform_name("Linux", "Linux version 5.15.90.1-microsoft-standard-WSL2", {}) == "wsl"
    assert detect_platform_name("Linux", "Linux version 6.1", {"WSL_DISTRO_NAME": "Ubuntu"}) == "wsl"
    assert detect_platform_name("Linux", "Linux version 6.1", {}) == "linux"
    assert detect_platform_name("Linux", "", {"AIWM_PLATFORM": "macos"}) == "macos"
    assert isinstance(make_platform_adapter("macos", home=Path("/h")), MacOSPlatformAdapter)
    assert isinstance(make_platform_adapter("windows", home=Path("/h")), WindowsPlatformAdapter)
    assert isinstance(make_platform_adapter("wsl", home=Path("/h")), WSLPlatformAdapter)
    assert isinstance(make_platform_adapter("linux", home=Path("/h")), LinuxPlatformAdapter)


def test_data_directories(tmp_path: Path):
    assert MacOSPlatformAdapter(home=tmp_path).get_data_directory() == tmp_path / ".ai-work-manager"
    assert WSLPlatformAdapter(home=tmp_path).get_data_directory() == tmp_path / ".ai-work-manager"
    win = WindowsPlatformAdapter(home=tmp_path, env={"LOCALAPPDATA": str(tmp_path / "Local")})
    assert win.get_data_directory() == tmp_path / "Local" / "AIWorkManager"
    assert (
        WindowsPlatformAdapter(home=tmp_path, env={}).get_data_directory()
        == tmp_path / "AppData" / "Local" / "AIWorkManager"
    )


def test_macos_launchd_and_notifications(tmp_path: Path):
    runner = FakeRunner()
    adapter = MacOSPlatformAdapter(runner=runner, home=tmp_path)
    path = Path(adapter.install_autostart(spec(tmp_path)))
    assert path.exists() and path.parent == tmp_path / "Library" / "LaunchAgents"
    import plistlib

    plist = plistlib.loads(path.read_bytes())
    assert plist["ProgramArguments"][-1] == "start" and plist["RunAtLoad"] is True
    assert ["launchctl", "load", str(path)] in runner.calls
    assert adapter.is_autostart_installed("com.aiworkmanager.test")
    assert adapter.remove_autostart("com.aiworkmanager.test") and not path.exists()
    assert adapter.show_notification("Title", 'Body "quoted"')
    assert runner.calls[-1][0] == "osascript" and 'with title "Title"' in runner.calls[-1][-1]
    assert adapter.open_file(tmp_path / "a.md") and runner.calls[-1][0] == "open"
    info = adapter.get_platform_info()
    assert info.autostart_method == "launchd" and info.name == "macos"


def test_windows_task_scheduler_and_toast(tmp_path: Path):
    runner = FakeRunner()
    adapter = WindowsPlatformAdapter(runner=runner, home=tmp_path, env={"LOCALAPPDATA": str(tmp_path)})
    name = adapter.install_autostart(spec(tmp_path))
    create = runner.calls[-1]
    assert create[:2] == ["schtasks.exe", "/Create"] and "ONLOGON" in create and name in create
    wrapper = adapter.wrapper_path(spec(tmp_path))
    assert wrapper.exists() and str(wrapper) in create[-1]
    body = wrapper.read_text()
    assert (
        'cd /d "' in body
        and "set AIWM_ENV_FILE=" in body
        and "aiwm start" in body
        and "autostart.log" in body
    )
    assert adapter.is_autostart_installed("com.aiworkmanager.test") and runner.calls[-1][1] == "/Query"
    assert adapter.remove_autostart("com.aiworkmanager.test") and runner.calls[-1][1] == "/Delete"
    assert adapter.show_notification("Hi", "It's done")
    assert (
        runner.calls[-1][0] == "powershell.exe"
        and "ToastNotification" in runner.calls[-1][-1]
        and "It''s done" in runner.calls[-1][-1]
    )
    failing = WindowsPlatformAdapter(runner=FakeRunner(returncode=1), home=tmp_path, env={})
    import pytest

    with pytest.raises(RuntimeError):
        failing.install_autostart(spec(tmp_path))


def test_linux_systemd_and_profile_fallback(tmp_path: Path):
    runner = FakeRunner(stdout="running")
    adapter = LinuxPlatformAdapter(runner=runner, home=tmp_path)
    adapter._which = lambda b: "/usr/bin/systemctl" if b == "systemctl" else None  # type: ignore[method-assign]
    path = Path(adapter.install_autostart(spec(tmp_path)))
    assert path == tmp_path / ".config" / "systemd" / "user" / "com.aiworkmanager.test.service"
    unit = path.read_text()
    assert "ExecStart=/usr/bin/uv run aiwm start" in unit and "RestartPreventExitStatus=2" in unit
    assert ["systemctl", "--user", "enable", "com.aiworkmanager.test.service"] in runner.calls
    assert not any("--now" in call for call in runner.calls)  # never start a second instance while running
    assert adapter.is_autostart_installed("com.aiworkmanager.test")
    assert adapter.remove_autostart("com.aiworkmanager.test") and not path.exists()
    # no systemd -> ~/.profile block
    no_systemd = LinuxPlatformAdapter(runner=FakeRunner(returncode=1), home=tmp_path)
    no_systemd._which = lambda b: None  # type: ignore[method-assign]
    profile = Path(no_systemd.install_autostart(spec(tmp_path)))
    assert profile == tmp_path / ".profile" and "aiwm start" in profile.read_text()
    assert no_systemd.is_autostart_installed("com.aiworkmanager.test")
    assert no_systemd.remove_autostart("com.aiworkmanager.test") and "aiwm start" not in profile.read_text()
    assert not no_systemd.show_notification("x", "y")  # notify-send missing


def test_wsl_bridges_to_windows_host(tmp_path: Path):
    runner = FakeRunner()
    adapter = WSLPlatformAdapter(runner=runner, home=tmp_path)
    adapter._which = lambda b: "/usr/bin/powershell.exe" if b == "powershell.exe" else None  # type: ignore[method-assign]
    assert adapter.open_browser("http://127.0.0.1:8765")
    assert runner.calls[-1][0] == "powershell.exe" and "Start-Process" in runner.calls[-1][-1]
    assert adapter.show_notification("Hello", "from WSL")
    assert "ToastNotification" in runner.calls[-1][-1]
    assert adapter.autostart_method == "profile_script"
    info = adapter.get_platform_info()
    assert (
        info.name == "wsl"
        and info.details["windows_bridge"] == "yes"
        and info.notification_method == "windows_toast_bridge"
    )
    # wslview preferred when available
    adapter._which = lambda b: "/usr/bin/wslview" if b == "wslview" else None  # type: ignore[method-assign]
    adapter.open_browser("http://x")
    assert runner.calls[-1] == ["wslview", "http://x"]
