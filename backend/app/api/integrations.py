from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.deps import get_ctx, get_session
from app.api.serializers import integration_out
from app.context import AppContext
from app.integrations.mcp.adapters import list_adapters
from app.integrations.mcp.config import ConnectionConfig
from app.schemas.common import Message
from app.schemas.integrations import (
    AdapterPresetOut,
    ConnectionTestOut,
    IntegrationCreate,
    IntegrationOut,
    IntegrationUpdate,
    ToolOut,
    ToolPermissionIn,
)
from app.services.integration_service import IntegrationService

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _registry(ctx: AppContext):
    if ctx.mcp_registry is None:
        raise HTTPException(status_code=503, detail="MCP registry is not available")
    return ctx.mcp_registry


def _out(service: IntegrationService, ctx: AppContext, row) -> IntegrationOut:
    authorized = False
    if ctx.mcp_registry is not None and row.auth_type == "oauth2":
        authorized = ctx.mcp_registry.oauth_authorized(ConnectionConfig.from_model(row))
    return integration_out(row, service.has_secret(row), authorized)


@router.get("", response_model=list[IntegrationOut])
def list_integrations(session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    service = IntegrationService(session, ctx.secret_store)
    return [_out(service, ctx, r) for r in service.list()]


@router.get("/presets", response_model=list[AdapterPresetOut])
def presets():
    result = []
    for adapter in list_adapters():
        preset = adapter.preset()
        result.append(
            AdapterPresetOut(
                adapter=preset.adapter,
                label=preset.label,
                description=preset.description,
                transport=preset.transport,
                command=preset.command,
                args=preset.args,
                url=preset.url,
                auth_type=preset.auth_type,
                auth_config=preset.auth_config,
                env_hints=preset.env_hints,
                tool_permissions=[ToolPermissionIn(**p) for p in preset.tool_permissions],
            )
        )
    return result


@router.post("", response_model=IntegrationOut, status_code=201)
def create_integration(
    data: IntegrationCreate, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
):
    service = IntegrationService(session, ctx.secret_store)
    row = service.create(data)
    return _out(service, ctx, row)


@router.get("/{connection_id}", response_model=IntegrationOut)
def get_integration(
    connection_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
):
    service = IntegrationService(session, ctx.secret_store)
    return _out(service, ctx, service.get(connection_id))


@router.patch("/{connection_id}", response_model=IntegrationOut)
def update_integration(
    connection_id: str,
    data: IntegrationUpdate,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    service = IntegrationService(session, ctx.secret_store)
    row = service.update(connection_id, data)
    session.commit()
    if ctx.mcp_registry is not None:
        ctx.mcp_registry.invalidate(connection_id)
    return _out(service, ctx, row)


@router.delete("/{connection_id}", response_model=Message)
def delete_integration(
    connection_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
):
    IntegrationService(session, ctx.secret_store).delete(connection_id)
    session.commit()
    if ctx.mcp_registry is not None:
        ctx.mcp_registry.invalidate(connection_id)
    return Message(message="deleted")


@router.post("/{connection_id}/test", response_model=ConnectionTestOut)
async def test_integration(
    connection_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
):
    row = IntegrationService(session, ctx.secret_store).get(connection_id)
    config = ConnectionConfig.from_model(row)
    session.close()
    result = await _registry(ctx).test_connection(config)
    return ConnectionTestOut(
        ok=result["ok"],
        message=result["message"],
        tools=[ToolOut(**t) for t in result["tools"]],
        server_name=result.get("server_name"),
        duration_ms=result.get("duration_ms", 0),
    )


@router.get("/{connection_id}/tools", response_model=list[ToolOut])
async def integration_tools(
    connection_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
):
    IntegrationService(session, ctx.secret_store).get(connection_id)
    session.close()
    try:
        tools = await _registry(ctx).list_tools(connection_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [ToolOut(**t) for t in tools]


@router.post("/{connection_id}/oauth/start", response_model=dict)
def oauth_start(connection_id: str, ctx: AppContext = Depends(get_ctx)):
    try:
        return _registry(ctx).begin_oauth(connection_id)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/oauth/callback")
async def oauth_callback(
    state: str, code: str | None = None, error: str | None = None, ctx: AppContext = Depends(get_ctx)
):
    if error or not code:
        return HTMLResponse(
            f"<h1>認証に失敗しました</h1><p>{error or 'code がありません'}</p>", status_code=400
        )
    try:
        connection_id = await _registry(ctx).complete_oauth(state, code)
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(f"<h1>認証に失敗しました</h1><p>{exc}</p>", status_code=400)
    ctx.broker.publish("integration.oauth", {"connection_id": connection_id, "status": "authorized"})
    return HTMLResponse("<h1>認証が完了しました</h1><p>このタブを閉じてアプリに戻ってください。</p>")


@router.post("/{connection_id}/oauth/revoke", response_model=Message)
def oauth_revoke(connection_id: str, ctx: AppContext = Depends(get_ctx)):
    registry = _registry(ctx)
    config = registry.config(connection_id)
    auth = registry.auth_for(config)
    if hasattr(auth, "revoke_local"):
        auth.revoke_local()
    registry.invalidate(connection_id)
    return Message(message="revoked")
