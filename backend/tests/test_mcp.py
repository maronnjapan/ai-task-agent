"""MCP tests (SPEC 30.4): stdio, Streamable HTTP, authentication, OAuth, permissions, reconnect."""

from __future__ import annotations

import asyncio
import socket
import sys
import threading
from pathlib import Path

import pytest
import uvicorn

from app.context import AppContext
from app.infrastructure.secrets.base import InMemorySecretProvider
from app.integrations.local_files import LocalFileAccessError, LocalFileSource
from app.integrations.mcp.adapters import get_adapter
from app.integrations.mcp.authentication import (
    ApiTokenAuth,
    BearerAuth,
    OAuth2Auth,
    OAuthError,
    OAuthFlowManager,
    OAuthTokens,
    build_auth,
)
from app.integrations.mcp.client import MCPClient, MCPConnectionError, ToolInfo
from app.integrations.mcp.config import ConnectionConfig
from app.integrations.mcp.registry import ApprovalPendingError, MCPRegistry, PermissionDeniedError
from app.integrations.mcp.transport import resolve_command
from app.integrations.permissions import classify_tool, requires_approval
from app.schemas.integrations import IntegrationCreate, ToolPermissionIn
from app.schemas.settings import LocalSourceSettings
from app.services.approval_service import ApprovalService
from app.services.integration_service import IntegrationService

SERVER = Path(__file__).parent / "mcp_test_server.py"


def stdio_config(name: str = "test-stdio", **overrides) -> ConnectionConfig:
    base = dict(
        id=f"id-{name}",
        name=name,
        adapter="generic",
        transport="stdio",
        command=sys.executable,
        args=[str(SERVER)],
        timeout_seconds=20,
    )
    base.update(overrides)
    return ConnectionConfig(**base)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class HttpServer:
    def __init__(self, bearer: str | None = None):
        from tests.mcp_test_server import build_http_app

        self.port = free_port()
        config = uvicorn.Config(
            build_http_app(bearer), host="127.0.0.1", port=self.port, log_level="warning", lifespan="on"
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        import time

        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=10)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"


@pytest.mark.asyncio
async def test_stdio_connection_list_and_call_tools():
    async with MCPClient(stdio_config()) as client:
        assert client.server_info["name"] == "aiwm-test-server"
        tools = {t.name: t for t in await client.list_tools()}
        assert {"search_messages", "get_item", "post_message", "fail"} <= set(tools)
        assert "query" in tools["search_messages"].input_schema["properties"]
        result = await client.call_tool("get_item", {"item_id": "42"})
        assert "hello from the MCP test server" in result.text and not result.is_error
        failed = await client.call_tool("fail", {})
        assert failed.is_error
        assert await client.ping()
        await client.reconnect()
        assert client.connected and (await client.call_tool("get_item", {"item_id": "1"})).text.startswith(
            "item 1"
        )
    assert not client.connected


@pytest.mark.asyncio
async def test_stdio_disconnect_and_errors():
    client = MCPClient(stdio_config(command="definitely-not-a-command-xyz", timeout_seconds=5))
    with pytest.raises(MCPConnectionError):
        await client.connect()
    assert not client.connected
    with pytest.raises(MCPConnectionError):
        await client.list_tools()
    assert resolve_command("python3").endswith("python3") or resolve_command("python3") == "python3"
    assert resolve_command("~/bin/tool").startswith("/")


@pytest.mark.asyncio
async def test_streamable_http_connection_with_bearer_auth():
    with HttpServer(bearer="secret-token") as http:
        config = ConnectionConfig(
            id="http1",
            name="http",
            transport="streamable_http",
            url=http.url,
            auth_type="bearer",
            timeout_seconds=20,
        )
        unauthorized = MCPClient(config, auth=BearerAuth(None))
        with pytest.raises(MCPConnectionError):
            await unauthorized.connect()
        async with MCPClient(config, auth=BearerAuth("secret-token")) as client:
            names = {t.name for t in await client.list_tools()}
            assert "search_messages" in names
            result = await client.call_tool("search_messages", {"query": "hello", "count": 2})
            assert "result for hello" in result.text
            assert (result.structured or {}).get("messages") or "messages" in result.text


@pytest.mark.asyncio
async def test_registry_search_service_and_permissions(ctx: AppContext):
    registry = MCPRegistry(ctx, approval_wait_seconds=0.0)
    with ctx.db.session() as s:
        row = IntegrationService(s, ctx.secret_store).create(
            IntegrationCreate(
                name="slack-test",
                adapter="slack",
                transport="stdio",
                command=sys.executable,
                args=[str(SERVER)],
                tool_permissions=[ToolPermissionIn(tool_name="fail", permission="read", enabled=False)],
            )
        )
        connection_id = row.id
    try:
        results = await registry.search_service("slack", "deploy", limit=2)
        assert (
            len(results) == 2
            and results[0]["channel"] == "general"
            and results[0]["url"].startswith("https://example.test/")
        )
        tools = await registry.list_tools(connection_id)
        perms = {t["name"]: (t["permission"], t["enabled"]) for t in tools}
        assert (
            perms["post_message"] == ("external_write", True)
            and perms["search_messages"] == ("read", True)
            and perms["fail"] == ("read", False)
        )
        with pytest.raises(PermissionDeniedError):
            await registry.call_tool(connection_id, "fail", {})
        # external_write requires approval: pending -> raises, approved -> executes, rejected -> denied
        with pytest.raises(ApprovalPendingError) as pending:
            await registry.call_tool(connection_id, "post_message", {"channel": "C1", "text": "hi"})
        with ctx.db.session() as s:
            approvals = ApprovalService(s)
            request = approvals.get(pending.value.approval_id)
            assert request.tool_name == "post_message" and request.status == "pending"
            approvals.resolve(request.id, True)
        registry.approval_wait_seconds = 5.0
        registry.approval_poll_seconds = 0.05

        async def approve_soon():
            await asyncio.sleep(0.2)
            with ctx.db.session() as s:
                for req in ApprovalService(s).list(status="pending"):
                    ApprovalService(s).resolve(req.id, True)

        task = asyncio.create_task(approve_soon())
        result = await registry.call_tool(connection_id, "post_message", {"channel": "C1", "text": "hi"})
        await task
        assert "posted to C1" in result.text

        async def reject_soon():
            await asyncio.sleep(0.2)
            with ctx.db.session() as s:
                for req in ApprovalService(s).list(status="pending"):
                    ApprovalService(s).resolve(req.id, False)

        task = asyncio.create_task(reject_soon())
        with pytest.raises(PermissionDeniedError):
            await registry.call_tool(connection_id, "post_message", {"channel": "C1", "text": "again"})
        await task
        # LangChain tool exposure for the Worker
        from app.agents.context import AgentContext

        lc_tools = await registry.langchain_tools(AgentContext(app=ctx, agent_type="worker"))
        names = {t.name for t in lc_tools}
        assert any(n.endswith("search_messages") for n in names) and not any(
            n.endswith("fail") for n in names
        )
        search_tool = next(t for t in lc_tools if t.name.endswith("get_item"))
        output = await search_tool.ainvoke({"item_id": "7"})
        assert "item 7" in output and output.startswith("[外部データ]")
        test_result = await registry.test_connection(registry.config(connection_id))
        assert test_result["ok"] and test_result["server_name"] == "aiwm-test-server"
        with ctx.db.session() as s:
            assert IntegrationService(s, ctx.secret_store).get(connection_id).last_tested_at
    finally:
        await registry.shutdown()


@pytest.mark.asyncio
async def test_registry_reports_connection_failure(ctx: AppContext):
    registry = MCPRegistry(ctx)
    with ctx.db.session() as s:
        row = IntegrationService(s, ctx.secret_store).create(
            IntegrationCreate(
                name="broken", transport="stdio", command="no-such-binary-abc", timeout_seconds=3
            )
        )
    result = await registry.test_connection(registry.config(row.id))
    assert not result["ok"] and result["message"]
    with pytest.raises(MCPConnectionError):
        await registry.search_service("slack", "x")
    await registry.shutdown()


def test_permission_classification_and_adapters():
    assert classify_tool("slack_search_messages") == "read"
    assert classify_tool("slack_post_message") == "external_write"
    assert classify_tool("jira_create_issue") == "external_write"
    assert classify_tool("get_page") == "read"
    assert requires_approval("external_write") and not requires_approval("read")
    jira = get_adapter("jira")
    tool = ToolInfo(
        name="jira_search",
        input_schema={"properties": {"jql": {"type": "string"}, "limit": {"type": "integer"}}},
    )
    args = jira.build_search_args(tool, "login bug", 5)
    assert args["jql"].startswith('text ~ "login bug"') and args["limit"] == 5
    assert jira.classify(ToolInfo(name="jira_add_comment")) == "external_write"
    confluence = get_adapter("confluence")
    tool = ToolInfo(name="confluence_search", input_schema={"properties": {"cql": {}, "limit": {}}})
    assert confluence.build_search_args(tool, "設計", 3)["cql"] == 'text ~ "設計"'
    drive = get_adapter("google_drive")
    assert (
        drive.normalize_item({"name": "Doc", "webViewLink": "https://drive/x", "mimeType": "text/plain"})[
            "url"
        ]
        == "https://drive/x"
    )
    slack = get_adapter("slack")
    normalised = slack.normalize_results(
        "search",
        type(
            "R",
            (),
            {
                "structured": {"messages": [{"text": "hi", "permalink": "p", "channel": {"name": "c"}}]},
                "text": "",
            },
        )(),
    )
    assert normalised[0]["snippet"] == "hi" and normalised[0]["channel"] == "c"
    assert get_adapter("unknown").name == "generic"
    assert [p.adapter for p in (a.preset() for a in (slack, drive, confluence, jira))] == [
        "slack",
        "google_drive",
        "confluence",
        "jira",
    ]


@pytest.mark.asyncio
async def test_oauth2_flow_exchange_refresh_and_headers():
    store = InMemorySecretProvider({"MCP_OAUTH1_SECRET": "client-secret"})
    calls: list[dict] = []

    async def fake_post(url, data, headers):
        calls.append({"url": url, "data": data})
        if data["grant_type"] == "authorization_code":
            assert (
                data["code"] == "the-code"
                and data["client_secret"] == "client-secret"
                and "code_verifier" in data
            )
            return {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 1, "token_type": "Bearer"}
        assert data["refresh_token"] == "rt-1"
        return {"access_token": "at-2", "expires_in": 3600}

    config = ConnectionConfig(
        id="oauth1",
        name="oauth",
        transport="streamable_http",
        url="http://x/mcp",
        auth_type="oauth2",
        auth_config={
            "client_id": "cid",
            "authorization_url": "https://auth.example/authorize",
            "token_url": "https://auth.example/token",
            "scope": "read",
        },
    )
    auth = build_auth(config, store, http_post=fake_post)
    assert isinstance(auth, OAuth2Auth) and not auth.is_ready()
    assert await auth.headers() == {}
    flows = OAuthFlowManager()
    pending = flows.begin(config.id)
    url = auth.authorization_url(pending.state, pending.code_verifier)
    assert (
        url.startswith("https://auth.example/authorize?")
        and "code_challenge=" in url
        and f"state={pending.state}" in url
        and "scope=read" in url
    )
    assert flows.take("bogus") is None
    taken = flows.take(pending.state)
    assert taken is not None and flows.take(pending.state) is None
    tokens = await auth.exchange_code("the-code", taken.code_verifier)
    assert tokens.access_token == "at-1" and auth.is_ready()
    stored = OAuthTokens.from_json(store.get_secret(config.oauth_secret_name()))
    assert stored and stored.refresh_token == "rt-1"
    import time

    auth._tokens.expires_at = time.time() - 10  # force expiry -> refresh on next header build
    headers = await auth.headers()
    assert headers == {"Authorization": "Bearer at-2"} and calls[-1]["data"]["grant_type"] == "refresh_token"
    assert (
        OAuthTokens.from_json(store.get_secret(config.oauth_secret_name())).refresh_token == "rt-1"
    )  # kept from previous
    assert await auth.on_unauthorized()
    auth.revoke_local()
    assert not auth.is_ready() and store.get_secret(config.oauth_secret_name()) is None
    with pytest.raises(OAuthError):
        await auth.refresh()
    api = build_auth(
        ConnectionConfig(id="k", name="k", auth_type="api_token", auth_config={"header_name": "X-Token"}),
        InMemorySecretProvider({"MCP_K_SECRET": "abc"}),
    )
    assert isinstance(api, ApiTokenAuth) and await api.headers() == {"X-Token": "abc"}


@pytest.mark.asyncio
async def test_oauth_registry_endpoints(ctx: AppContext, client):
    async def fake_post(url, data, headers):
        return {"access_token": "token-x", "expires_in": 3600}

    ctx.mcp_registry.http_post = fake_post
    created = client.post(
        "/api/integrations",
        json={
            "name": "oauth-http",
            "transport": "streamable_http",
            "url": "http://127.0.0.1:1/mcp",
            "auth_type": "oauth2",
            "auth_config": {
                "client_id": "cid",
                "authorization_url": "https://auth.example/a",
                "token_url": "https://auth.example/t",
            },
        },
    ).json()
    assert created["oauth_authorized"] is False
    start = client.post(f"/api/integrations/{created['id']}/oauth/start").json()
    assert start["authorization_url"].startswith("https://auth.example/a?")
    callback = client.get("/api/integrations/oauth/callback", params={"state": start["state"], "code": "abc"})
    assert callback.status_code == 200 and "完了" in callback.text
    assert client.get(f"/api/integrations/{created['id']}").json()["oauth_authorized"] is True
    assert (
        client.get("/api/integrations/oauth/callback", params={"state": "bad", "code": "abc"}).status_code
        == 400
    )
    assert client.post(f"/api/integrations/{created['id']}/oauth/revoke").json()["ok"]
    assert client.get(f"/api/integrations/{created['id']}").json()["oauth_authorized"] is False


def test_local_file_source(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "notes.md").write_text("# メモ\nOIDC の調査メモ\nPKCE は必須\n", encoding="utf-8")
    (root / "secret.key").write_text("not searchable", encoding="utf-8")
    (tmp_path / "outside.md").write_text("outside OIDC", encoding="utf-8")
    source = LocalFileSource(LocalSourceSettings(directories=[str(root)], extensions=[".md", "txt"]))
    hits = source.search("OIDC")
    assert len(hits) == 1 and hits[0].path.endswith("notes.md") and hits[0].line == 2
    assert source.search("調査 メモ")[0].line == 2
    assert source.read(str(root / "notes.md")).startswith("# メモ")
    with pytest.raises(LocalFileAccessError):
        source.read(str(tmp_path / "outside.md"))
    with pytest.raises(LocalFileAccessError):
        source.read(str(root / "secret.key"))
    with pytest.raises(LocalFileAccessError):
        source.read(str(root / ".." / "outside.md"))
    assert LocalFileSource(LocalSourceSettings(directories=[])).search("x") == []
