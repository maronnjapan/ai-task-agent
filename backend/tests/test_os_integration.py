"""Real-OS integration tests (SPEC 30.3).

These run only on the matching operating system (the CI matrix covers macOS, Windows and
Linux); elsewhere they are skipped. They touch the real Keychain / launchd / Task Scheduler /
systemd tooling with throw-away names and clean up after themselves.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.infrastructure.secrets.dotenv import DotEnvSecretProvider
from app.infrastructure.secrets.keychain import MacOSKeychainSecretProvider
from app.platform.base import AutostartSpec
from app.platform.factory import detect_platform_name, make_platform_adapter

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_WSL = IS_LINUX and detect_platform_name() == "wsl"


def _spec(tmp_path: Path, label: str) -> AutostartSpec:
    return AutostartSpec(
        label=label,
        command=[sys.executable, "-c", "print('aiwm autostart test')"],
        working_directory=tmp_path,
        log_directory=tmp_path / "logs",
        environment={"AIWM_ENV_FILE": str(tmp_path / ".env")},
    )


@pytest.mark.skipif(not IS_MAC, reason="macOS Keychain only")
def test_macos_keychain_roundtrip_with_real_security_cli():
    provider = MacOSKeychainSecretProvider(service=f"ai-work-manager-test-{uuid.uuid4().hex[:8]}")
    name = "OPENAI_API_KEY"
    try:
        assert provider.get_secret(name) is None
        provider.set_secret(name, "sk-test-keychain-value")
        assert provider.get_secret(name) == "sk-test-keychain-value"
        provider.set_secret(name, "sk-updated")  # -U updates in place
        assert provider.get_secret(name) == "sk-updated"
    finally:
        provider.delete_secret(name)
    assert provider.get_secret(name) is None


@pytest.mark.skipif(not IS_MAC, reason="launchd only")
def test_macos_launchd_plist_is_valid_and_loads(tmp_path: Path):
    adapter = make_platform_adapter("macos", home=tmp_path)
    label = f"com.aiworkmanager.test.{uuid.uuid4().hex[:8]}"
    path = Path(adapter.install_autostart(_spec(tmp_path, label)))
    try:
        assert path.exists()
        lint = subprocess.run(["plutil", "-lint", str(path)], capture_output=True, text=True)
        assert lint.returncode == 0, lint.stdout + lint.stderr
        assert adapter.is_autostart_installed(label)
    finally:
        adapter.remove_autostart(label)
    assert not path.exists()
    assert adapter.get_data_directory() == tmp_path / ".ai-work-manager"
    # Notification command runs (display may be unavailable on CI; only the invocation is asserted)
    adapter.show_notification("AI Work Manager", "test notification")


@pytest.mark.skipif(not IS_WIN, reason="Windows only")
def test_windows_dotenv_and_task_scheduler(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("SECRET_BACKEND=dotenv\nOPENAI_API_KEY=sk-windows-test\n", encoding="utf-8")
    assert DotEnvSecretProvider(env, env_fallback=False).get_secret("OPENAI_API_KEY") == "sk-windows-test"
    adapter = make_platform_adapter("windows", home=tmp_path, env=dict(os.environ))
    assert adapter.get_data_directory().name == "AIWorkManager"
    label = f"com.aiworkmanager.test.{uuid.uuid4().hex[:8]}"
    try:
        name = adapter.install_autostart(_spec(tmp_path, label))
    except RuntimeError as exc:  # no permission to create scheduled tasks on this runner
        pytest.skip(f"schtasks unavailable: {exc}")
    try:
        assert adapter.is_autostart_installed(label)
        assert adapter.wrapper_path(_spec(tmp_path, label)).exists()
        query = subprocess.run(["schtasks.exe", "/Query", "/TN", name], capture_output=True, text=True)
        assert query.returncode == 0
    finally:
        adapter.remove_autostart(label)
    assert not adapter.is_autostart_installed(label)
    adapter.show_notification("AI Work Manager", "test toast")


@pytest.mark.skipif(not IS_LINUX, reason="Linux / WSL only")
def test_linux_dotenv_and_autostart_method(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-linux-test\n", encoding="utf-8")
    provider = DotEnvSecretProvider(env, env_fallback=False)
    assert provider.get_secret("OPENAI_API_KEY") == "sk-linux-test"
    provider.set_secret("OPENAI_API_KEY", "sk-rotated")
    assert oct(env.stat().st_mode)[-3:] == "600"
    adapter = make_platform_adapter("wsl" if IS_WSL else "linux", home=tmp_path)
    info = adapter.get_platform_info()
    assert info.data_directory == str(tmp_path / ".ai-work-manager")
    assert info.autostart_method in ("systemd_user", "profile_script")
    label = f"com.aiworkmanager.test.{uuid.uuid4().hex[:8]}"
    location = Path(adapter.install_autostart(_spec(tmp_path, label)))
    try:
        assert location.exists() and adapter.is_autostart_installed(label)
    finally:
        adapter.remove_autostart(label)
    assert not adapter.is_autostart_installed(label)


@pytest.mark.skipif(not IS_WSL, reason="WSL only")
def test_wsl_windows_host_bridges():
    adapter = make_platform_adapter("wsl")
    info = adapter.get_platform_info()
    assert info.name == "wsl" and info.notification_method == "windows_toast_bridge"
    assert shutil.which("powershell.exe") or shutil.which("wslview") or shutil.which("cmd.exe")
    adapter.show_notification("AI Work Manager", "WSL bridge test")
