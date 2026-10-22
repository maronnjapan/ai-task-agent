"""FastAPI application factory and bootstrap (SPEC 4.5, 6)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from app import __version__
from app.api.router import api_router
from app.api.security import LocalApiProtectionMiddleware
from app.api.session import COOKIE_MAX_AGE, COOKIE_NAME, QUERY_PARAM, SessionGuard, load_or_create_token
from app.config import PROJECT_ROOT, Settings, get_settings
from app.context import AppContext
from app.infrastructure.database import Database
from app.infrastructure.events import EventBroker
from app.infrastructure.logging import configure_logging
from app.infrastructure.paths import build_paths
from app.infrastructure.secrets.base import SecretProvider
from app.infrastructure.secrets.bootstrap import (
    SecretBootstrap,
    console_confirmer,
    console_prompter,
    select_secret_provider,
)
from app.llm.providers import LLMFactory
from app.platform import PlatformAdapter, make_platform_adapter
from app.services.errors import ServiceError

log = logging.getLogger(__name__)

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def required_llm_providers(db: Database, settings: Settings) -> list[str]:
    from app.services.settings_service import SettingsService

    with db.session() as session:
        llm = SettingsService(session, settings).get_llm()
    providers = {llm.manager.provider, llm.worker.provider, llm.review.provider}
    return sorted(p for p in providers if p and p != "fake")


def build_context(
    settings: Settings | None = None,
    data_dir: Path | None = None,
    interactive: bool = False,
    platform: PlatformAdapter | None = None,
    secret_store: SecretProvider | None = None,
    provider_override: str | None = None,
    use_migrations: bool = True,
) -> AppContext:
    settings = settings or get_settings()
    platform = platform or make_platform_adapter()
    paths = build_paths(data_dir or settings.resolved_data_dir()).ensure()
    configure_logging(paths.logs, settings.log_level)
    log.info("AI Work Manager %s starting (platform=%s, data=%s)", __version__, platform.name, paths.root)
    db = Database(paths.database, use_migrations=use_migrations)
    store = secret_store or select_secret_provider(settings.secret_backend, platform.name, settings.env_file)
    bootstrap = SecretBootstrap(
        store,
        prompter=console_prompter if interactive else None,
        confirmer=console_confirmer(
            "macOS Keychain" if getattr(store, "name", "") in ("keychain", "layered") else ".env"
        )
        if interactive
        else None,
        interactive=interactive,
    )
    result = bootstrap.run(required_llm_providers(db, settings))
    if result.missing:
        log.warning("API keys not configured: %s (configure them in Settings)", ", ".join(result.missing))
    override = provider_override or settings.aiwm_llm_provider_override
    ctx = AppContext(
        settings=settings,
        paths=paths,
        db=db,
        broker=EventBroker(),
        platform=platform,
        secrets=result.secrets,
        secret_store=store,
    )
    ctx.llm_factory = LLMFactory(ctx.secrets, provider_override=override)
    from app.integrations.mcp.registry import MCPRegistry

    ctx.mcp_registry = MCPRegistry(ctx)
    return ctx


def session_token(ctx: AppContext) -> str | None:
    if not ctx.settings.api_session_token_required:
        return None
    token = ctx.extras.get("session_token")
    if not token:
        token = load_or_create_token(ctx.paths.config / "session.token")
        ctx.extras["session_token"] = token
    return token


def session_url(ctx: AppContext) -> str:
    host = "127.0.0.1" if ctx.settings.app_host in ("0.0.0.0", "::", "") else ctx.settings.app_host
    base = f"http://{host}:{ctx.settings.app_port}/"
    token = session_token(ctx)
    return f"{base}?{QUERY_PARAM}={token}" if token else base


def write_settings_snapshot(ctx: AppContext) -> Path:
    """Mirror the effective settings to ``config/settings.json`` (SPEC 5.3) for inspection and backups."""
    import json

    from app.services.settings_service import SettingsService

    with ctx.db.session() as session:
        service = SettingsService(session, ctx.settings)
        snapshot = {
            "llm": service.get_llm().model_dump(),
            "manager": service.get_manager().model_dump(),
            "notifications": service.get_notifications().model_dump(),
            "local_sources": service.get_local_sources().model_dump(),
            "backup": service.get_backup().model_dump(),
            "app": {
                "host": ctx.settings.app_host,
                "port": ctx.settings.app_port,
                "data_dir": str(ctx.paths.root),
            },
        }
    ctx.paths.config.mkdir(parents=True, exist_ok=True)
    ctx.paths.settings_file.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return ctx.paths.settings_file


def create_app(
    ctx: AppContext | None = None, serve_frontend: bool = True, extra_hosts: set[str] | None = None
) -> FastAPI:
    ctx = ctx or build_context()
    guard = SessionGuard(session_token(ctx))
    write_settings_snapshot(ctx)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from app.orchestrator.runner import Orchestrator

        if not ctx.settings.aiwm_disable_orchestrator:
            orchestrator = Orchestrator(ctx)
            orchestrator.enabled = ctx.settings.auto_start_manager
            ctx.orchestrator = orchestrator
            await orchestrator.start()
        try:
            yield
        finally:
            if ctx.orchestrator is not None:
                await ctx.orchestrator.stop()
            if ctx.mcp_registry is not None:
                await ctx.mcp_registry.shutdown()
            ctx.db.dispose()

    app = FastAPI(
        title="Autonomous AI Work Manager",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.ctx = ctx
    app.add_middleware(
        LocalApiProtectionMiddleware,
        app_host=ctx.settings.app_host,
        app_port=ctx.settings.app_port,
        extra_hosts=extra_hosts,
        session_guard=guard,
    )

    def _attach_session(request: Request, response):
        """Issue the session cookie when the tokenised URL is opened (or renew an existing one)."""
        if not guard.enabled:
            return response
        presented = request.query_params.get(QUERY_PARAM)
        if guard.matches(presented) or guard.matches(request.cookies.get(COOKIE_NAME)):
            response.set_cookie(
                COOKIE_NAME,
                guard.token or "",
                max_age=COOKIE_MAX_AGE,
                httponly=True,
                samesite="strict",
                path="/",
            )
        return response

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    app.include_router(api_router)

    if serve_frontend and FRONTEND_DIST.exists():
        assets = FRONTEND_DIST / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(request: Request, full_path: str):
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            candidate = (FRONTEND_DIST / full_path).resolve()
            if full_path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
                return FileResponse(candidate)
            return _attach_session(request, FileResponse(FRONTEND_DIST / "index.html"))

    else:

        @app.get("/", include_in_schema=False)
        async def root(request: Request):
            return _attach_session(
                request,
                JSONResponse(
                    {
                        "name": "Autonomous AI Work Manager",
                        "version": __version__,
                        "frontend": "not built - run `npm run build` in frontend/",
                        "api_docs": "/api/docs",
                    }
                ),
            )

    return app


def acquire_instance_lock(settings: Settings | None = None):
    """Refuse to start a second backend before any migration or interactive prompt runs (SPEC 6.3)."""
    from app.infrastructure.single_instance import AlreadyRunningError, InstanceLock

    settings = settings or get_settings()
    paths = build_paths(settings.resolved_data_dir()).ensure()
    lock = InstanceLock(paths.lock_file)
    try:
        lock.acquire()
    except AlreadyRunningError:
        log.error("Another AI Work Manager instance is already running for %s", paths.root)
        raise SystemExit(2) from None
    return lock


def serve(ctx: AppContext | None = None, open_browser: bool = False, lock=None) -> None:
    import uvicorn

    ctx = ctx or build_context(interactive=False)
    lock = lock or acquire_instance_lock(ctx.settings)
    ctx.paths.pid_file.write_text(str(__import__("os").getpid()))
    app = create_app(ctx)
    url = session_url(ctx)
    log.info("UI: %s", url)
    if open_browser:
        import threading

        threading.Timer(1.5, lambda: ctx.platform.open_browser(url)).start()
    try:
        uvicorn.run(
            app,
            host=ctx.settings.app_host,
            port=ctx.settings.app_port,
            log_level=ctx.settings.log_level.lower(),
            access_log=False,
        )
    finally:
        lock.release()
        try:
            ctx.paths.pid_file.unlink()
        except OSError:
            pass


app = None  # created lazily by ``aiwm start``; import ``create_app`` for programmatic use
