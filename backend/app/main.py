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


def create_app(ctx: AppContext | None = None, serve_frontend: bool = True) -> FastAPI:
    ctx = ctx or build_context()

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
        extra_hosts={"testserver"},
    )

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    app.include_router(api_router)

    if serve_frontend and FRONTEND_DIST.exists():
        assets = FRONTEND_DIST / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            candidate = (FRONTEND_DIST / full_path).resolve()
            if full_path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

    else:

        @app.get("/", include_in_schema=False)
        async def root():
            return JSONResponse(
                {
                    "name": "Autonomous AI Work Manager",
                    "version": __version__,
                    "frontend": "not built - run `npm run build` in frontend/",
                    "api_docs": "/api/docs",
                }
            )

    return app


def serve(ctx: AppContext | None = None, open_browser: bool = False) -> None:
    import uvicorn

    from app.infrastructure.single_instance import AlreadyRunningError, InstanceLock

    ctx = ctx or build_context(interactive=False)
    lock = InstanceLock(ctx.paths.lock_file)
    try:
        lock.acquire()
    except AlreadyRunningError:
        log.error("Another AI Work Manager instance is already running for %s", ctx.paths.root)
        raise SystemExit(2) from None
    ctx.paths.pid_file.write_text(str(__import__("os").getpid()))
    app = create_app(ctx)
    url = f"http://{ctx.settings.app_host}:{ctx.settings.app_port}"
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
