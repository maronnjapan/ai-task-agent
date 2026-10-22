"""Command line entry point: ``aiwm <command>``."""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

from app import __version__


def autostart_command() -> list[str]:
    """Command used by the OS autostart entry to launch the backend."""
    uv = _which("uv")
    backend = Path(__file__).resolve().parent.parent
    if uv:
        return [uv, "run", "--project", str(backend), "aiwm", "start"]
    return [sys.executable, "-m", "app.cli", "start"]


def _which(binary: str) -> str | None:
    import shutil

    return shutil.which(binary)


def cmd_start(args: argparse.Namespace) -> int:
    from app.main import build_context, serve

    ctx = build_context(interactive=not args.no_prompt and sys.stdin.isatty())
    serve(ctx, open_browser=args.open)
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    from app.main import build_context

    ctx = build_context(interactive=True)
    print()
    print(f"Data directory : {ctx.paths.root}")
    print(f"Secret backend : {getattr(ctx.secret_store, 'name', '?')}")
    print(f"Env file       : {ctx.settings.env_file}")
    from app.infrastructure.secrets.bootstrap import secret_name_for_provider

    for provider in ("openai", "anthropic", "google"):
        name = secret_name_for_provider(provider)
        print(f"{name:<18}: {'configured' if ctx.secrets.get_secret(name) or ctx.secret_store.get_secret(name) else 'not set'}")
    print()
    print("Setup complete. Start the app with: aiwm start")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    from app.config import get_settings

    settings = get_settings()
    from app.infrastructure.paths import build_paths

    paths = build_paths(settings.resolved_data_dir())
    if not paths.pid_file.exists():
        print("AI Work Manager is not running (no pid file).")
        return 1
    pid = int(paths.pid_file.read_text().strip() or 0)
    try:
        if os.name == "nt":  # pragma: no cover
            os.kill(pid, signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        else:
            os.kill(pid, signal.SIGTERM)
        print(f"Sent stop signal to pid {pid}.")
        return 0
    except ProcessLookupError:
        print("Process not found; removing stale pid file.")
        paths.pid_file.unlink(missing_ok=True)
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    import json
    import urllib.request

    from app.config import get_settings

    settings = get_settings()
    url = f"http://{settings.app_host}:{settings.app_port}/api/system/status"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - local URL
            data = json.loads(response.read())
    except Exception as exc:  # noqa: BLE001
        print(f"Backend not reachable at {url}: {exc}")
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    from app.config import get_settings
    from app.infrastructure.backup import BackupService
    from app.infrastructure.paths import build_paths

    paths = build_paths(get_settings().resolved_data_dir()).ensure()
    info = BackupService(paths, __version__).create(Path(args.directory) if args.directory else None, label=args.label)
    print(f"Backup written: {info.path} ({info.size_bytes} bytes)")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    from app.config import get_settings
    from app.infrastructure.backup import BackupService
    from app.infrastructure.paths import build_paths

    paths = build_paths(get_settings().resolved_data_dir()).ensure()
    if paths.pid_file.exists():
        print("Stop the running backend before restoring.")
        return 1
    if not args.yes:
        answer = input(f"Restore {args.archive}? The current data will be backed up first. [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            return 1
    safety = BackupService(paths, __version__).restore(Path(args.archive))
    print(f"Restored from {args.archive}. Previous data saved to {safety.path}.")
    return 0


def cmd_autostart(args: argparse.Namespace) -> int:
    from app.api.settings import AUTOSTART_LABEL
    from app.config import get_settings
    from app.infrastructure.paths import build_paths
    from app.platform import make_platform_adapter
    from app.platform.base import AutostartSpec

    settings = get_settings()
    paths = build_paths(settings.resolved_data_dir()).ensure()
    platform = make_platform_adapter()
    if args.action == "install":
        spec = AutostartSpec(label=AUTOSTART_LABEL, command=autostart_command(), working_directory=settings.env_file.parent, log_directory=paths.logs, environment={"AIWM_ENV_FILE": str(settings.env_file)})
        print(f"Autostart installed: {platform.install_autostart(spec)}")
    elif args.action == "remove":
        print("Autostart removed." if platform.remove_autostart(AUTOSTART_LABEL) else "Autostart was not installed.")
    else:
        print("installed" if platform.is_autostart_installed(AUTOSTART_LABEL) else "not installed")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    from app.config import get_settings
    from app.infrastructure.database import Database
    from app.infrastructure.paths import build_paths

    paths = build_paths(get_settings().resolved_data_dir()).ensure()
    Database(paths.database, use_migrations=True).dispose()
    print(f"Database up to date: {paths.database}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aiwm", description="Autonomous AI Work Manager")
    parser.add_argument("--version", action="version", version=f"aiwm {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="start the backend (serves the UI)")
    start.add_argument("--open", action="store_true", help="open the browser after start")
    start.add_argument("--no-prompt", action="store_true", help="never prompt for API keys")
    start.set_defaults(func=cmd_start)
    sub.add_parser("setup", help="interactive first-time setup (API keys)").set_defaults(func=cmd_setup)
    sub.add_parser("stop", help="stop a running backend").set_defaults(func=cmd_stop)
    sub.add_parser("status", help="show backend status").set_defaults(func=cmd_status)
    backup = sub.add_parser("backup", help="create a backup archive")
    backup.add_argument("--directory")
    backup.add_argument("--label")
    backup.set_defaults(func=cmd_backup)
    restore = sub.add_parser("restore", help="restore from a backup archive")
    restore.add_argument("archive")
    restore.add_argument("--yes", action="store_true")
    restore.set_defaults(func=cmd_restore)
    auto = sub.add_parser("autostart", help="manage OS autostart")
    auto.add_argument("action", choices=["install", "remove", "status"])
    auto.set_defaults(func=cmd_autostart)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(func=cmd_migrate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
