from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_ctx, get_session
from app.context import AppContext
from app.infrastructure.secrets.bootstrap import secret_name_for_provider
from app.schemas.common import Message
from app.schemas.settings import ApiKeyDelete, ApiKeyUpdate, ProviderKeyStatus, SettingsOut, SettingsPatch
from app.schemas.system import AutostartRequest
from app.services.audit_service import AuditService
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api/settings", tags=["settings"])

AUTOSTART_LABEL = "com.aiworkmanager.backend"


def _key_status(ctx: AppContext) -> list[ProviderKeyStatus]:
    backend = getattr(ctx.secret_store, "name", "unknown")
    result = []
    for provider in ("openai", "anthropic", "google"):
        name = secret_name_for_provider(provider)
        configured = bool(ctx.secrets.get_secret(name) or ctx.secret_store.get_secret(name))
        result.append(
            ProviderKeyStatus(provider=provider, secret_name=name, configured=configured, backend=backend)
        )
    return result


def _settings_out(session: Session, ctx: AppContext) -> SettingsOut:
    service = SettingsService(session, ctx.settings)
    return SettingsOut(
        llm=service.get_llm(),
        manager=service.get_manager(),
        notifications=service.get_notifications(),
        local_sources=service.get_local_sources(),
        backup=service.get_backup(),
        platform=ctx.platform.get_platform_info().to_dict(),
        secret_backend=getattr(ctx.secret_store, "name", "unknown"),
        api_keys=_key_status(ctx),
        autostart_installed=ctx.platform.is_autostart_installed(AUTOSTART_LABEL),
        data_directory=str(ctx.paths.root),
        env_file=str(ctx.settings.env_file),
        app={
            "host": ctx.settings.app_host,
            "port": ctx.settings.app_port,
            "auto_start_manager": ctx.settings.auto_start_manager,
            "providers": ctx.llm_factory.providers() if ctx.llm_factory else [],
        },
    )


@router.get("", response_model=SettingsOut)
def get_settings(session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    return _settings_out(session, ctx)


@router.patch("", response_model=SettingsOut)
def patch_settings(
    data: SettingsPatch, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
):
    service = SettingsService(session, ctx.settings)
    changed = []
    if data.llm is not None:
        service.set_llm(data.llm)
        changed.append("llm")
    if data.manager is not None:
        service.set_manager(data.manager)
        changed.append("manager")
    if data.notifications is not None:
        service.set_notifications(data.notifications)
        changed.append("notifications")
    if data.local_sources is not None:
        service.set_local_sources(data.local_sources)
        changed.append("local_sources")
    if data.backup is not None:
        service.set_backup(data.backup)
        changed.append("backup")
    AuditService(session).record("settings.updated", "settings", None, "user", {"sections": changed})
    session.commit()
    from app.main import write_settings_snapshot

    write_settings_snapshot(ctx)
    ctx.broker.publish("settings.updated", {"sections": changed})
    return _settings_out(session, ctx)


@router.post("/api-keys", response_model=list[ProviderKeyStatus])
def set_api_key(
    data: ApiKeyUpdate, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
):
    name = secret_name_for_provider(data.provider)
    from app.infrastructure.logging import register_secret

    try:
        ctx.secret_store.set_secret(name, data.api_key)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not store the key: {exc}") from exc
    ctx.secrets.set_secret(name, data.api_key)
    register_secret(data.api_key)
    AuditService(session).record("secret.updated", "secret", name, "user")
    if ctx.orchestrator is not None:
        ctx.orchestrator.status.llm_issue = None
        ctx.orchestrator.trigger("manual_run", {"reason": "api_key_configured"})
    return _key_status(ctx)


@router.delete("/api-keys", response_model=list[ProviderKeyStatus])
def delete_api_key(
    data: ApiKeyDelete, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
):
    name = secret_name_for_provider(data.provider)
    ctx.secret_store.delete_secret(name)
    ctx.secrets.delete_secret(name)
    AuditService(session).record("secret.deleted", "secret", name, "user")
    return _key_status(ctx)


@router.post("/autostart", response_model=Message)
def set_autostart(
    data: AutostartRequest, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
):
    from app.cli import autostart_command
    from app.platform.base import AutostartSpec

    try:
        if data.enabled:
            spec = AutostartSpec(
                label=AUTOSTART_LABEL,
                command=autostart_command(),
                working_directory=ctx.settings.env_file.parent,
                log_directory=ctx.paths.logs,
                environment={"AIWM_ENV_FILE": str(ctx.settings.env_file)},
            )
            location = ctx.platform.install_autostart(spec)
            message = f"自動起動を登録しました: {location}"
        else:
            removed = ctx.platform.remove_autostart(AUTOSTART_LABEL)
            message = "自動起動を解除しました" if removed else "自動起動は登録されていませんでした"
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    AuditService(session).record("autostart.updated", "system", None, "user", {"enabled": data.enabled})
    return Message(message=message, data={"installed": ctx.platform.is_autostart_installed(AUTOSTART_LABEL)})
