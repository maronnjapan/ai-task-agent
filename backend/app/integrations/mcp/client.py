"""Generic MCP client implementing the MCPConnector protocol (SPEC 17.7).

The MCP session lives in a dedicated asyncio task so that the anyio cancel
scopes used by the SDK are always entered and exited from the same task,
regardless of which task issues ``call_tool``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.integrations.mcp.authentication import AuthStrategy, NoAuth
from app.integrations.mcp.config import ConnectionConfig
from app.integrations.mcp.transport import open_transport

log = logging.getLogger(__name__)


@dataclass
class ToolInfo:
    name: str
    description: str | None = None
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    text: str
    is_error: bool = False
    structured: Any = None
    raw: Any = None


class MCPConnector(Protocol):
    async def connect(self) -> None: ...

    async def list_tools(self) -> list[ToolInfo]: ...

    async def call_tool(self, name: str, arguments: dict) -> ToolResult: ...

    async def disconnect(self) -> None: ...


class MCPConnectionError(RuntimeError):
    pass


class MCPUnauthorized(MCPConnectionError):
    pass


@dataclass
class _Request:
    kind: str
    name: str | None = None
    arguments: dict[str, Any] | None = None
    future: asyncio.Future | None = None


def result_to_text(result: Any) -> ToolResult:
    """Normalise ``CallToolResult`` into text (+ structured content)."""
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        item_type = getattr(item, "type", None)
        if item_type == "text":
            parts.append(str(getattr(item, "text", "")))
        elif item_type == "resource":
            resource = getattr(item, "resource", None)
            text = getattr(resource, "text", None)
            if text:
                parts.append(str(text))
            else:
                parts.append(f"[resource {getattr(resource, 'uri', '')}]")
        else:
            parts.append(f"[{item_type or 'content'}]")
    structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    text = "\n".join(p for p in parts if p)
    if not text and structured is not None:
        import json

        text = json.dumps(structured, ensure_ascii=False)
    return ToolResult(
        text=text,
        is_error=bool(getattr(result, "is_error", False) or getattr(result, "isError", False)),
        structured=structured,
        raw=result,
    )


class MCPClient:
    def __init__(
        self, config: ConnectionConfig, auth: AuthStrategy | None = None, read_timeout: float | None = None
    ):
        self.config = config
        self.auth = auth or NoAuth()
        self.read_timeout = read_timeout or float(config.timeout_seconds)
        self._queue: asyncio.Queue[_Request] | None = None
        self._task: asyncio.Task | None = None
        self._ready: asyncio.Future | None = None
        self.server_info: dict[str, Any] = {}
        self.instructions: str | None = None
        self._tools_cache: list[ToolInfo] | None = None

    @property
    def connected(self) -> bool:
        return self._task is not None and not self._task.done()

    # --- lifecycle --------------------------------------------------
    async def connect(self) -> None:
        """Open the session; a 401/403 during initialisation triggers one token refresh and retry."""
        if self.connected:
            return
        try:
            await self._connect_once()
        except MCPUnauthorized:
            if not await self.auth.on_unauthorized():
                raise
            await self._connect_once()

    async def _connect_once(self) -> None:
        loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._ready = loop.create_future()
        self._task = asyncio.create_task(self._session_task(), name=f"mcp-{self.config.name}")
        try:
            await asyncio.wait_for(asyncio.shield(self._ready), timeout=self.config.timeout_seconds + 5)
        except TimeoutError as exc:
            await self.disconnect()
            raise MCPConnectionError(f"timeout connecting to {self.config.name}") from exc
        except Exception as exc:
            await self.disconnect()
            if is_unauthorized(exc):
                raise MCPUnauthorized(f"{self.config.name} rejected the credentials: {exc}") from exc
            raise MCPConnectionError(f"failed to connect to {self.config.name}: {exc}") from exc

    async def disconnect(self) -> None:
        task, queue = self._task, self._queue
        self._task, self._queue, self._ready = None, None, None
        self._tools_cache = None
        if task is None:
            return
        if queue is not None and not task.done():
            await queue.put(_Request(kind="shutdown"))
            try:
                await asyncio.wait_for(task, timeout=10)
                return
            except (TimeoutError, Exception):  # noqa: BLE001
                pass
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def __aenter__(self) -> MCPClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.disconnect()

    # --- operations -------------------------------------------------
    async def _request(self, request: _Request) -> Any:
        if not self.connected or self._queue is None:
            raise MCPConnectionError(f"{self.config.name} is not connected")
        loop = asyncio.get_running_loop()
        request.future = loop.create_future()
        await self._queue.put(request)
        return await request.future

    async def list_tools(self, use_cache: bool = True) -> list[ToolInfo]:
        if use_cache and self._tools_cache is not None:
            return self._tools_cache
        result = await self._request(_Request(kind="list_tools"))
        tools = [
            ToolInfo(
                name=t.name,
                description=t.description,
                input_schema=dict(getattr(t, "input_schema", None) or getattr(t, "inputSchema", {}) or {}),
            )
            for t in result.tools
        ]
        self._tools_cache = tools
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        try:
            raw = await self._request(_Request(kind="call_tool", name=name, arguments=arguments or {}))
        except MCPUnauthorized:
            if await self.auth.on_unauthorized():
                await self.reconnect()
                raw = await self._request(_Request(kind="call_tool", name=name, arguments=arguments or {}))
            else:
                raise
        return result_to_text(raw)

    async def reconnect(self) -> None:
        await self.disconnect()
        await self.connect()

    async def ping(self) -> bool:
        try:
            await self._request(_Request(kind="ping"))
            return True
        except Exception:  # noqa: BLE001
            return False

    # --- session task -----------------------------------------------
    async def _session_task(self) -> None:
        from mcp import ClientSession

        assert self._queue is not None and self._ready is not None
        queue, ready = self._queue, self._ready
        try:
            headers = await self.auth.headers()
            async with open_transport(self.config, headers) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=self.read_timeout) as session:
                    init = await session.initialize()
                    info = getattr(init, "server_info", None) or getattr(init, "serverInfo", None)
                    self.server_info = {
                        "name": getattr(info, "name", None),
                        "version": getattr(info, "version", None),
                    }
                    self.instructions = getattr(init, "instructions", None)
                    if not ready.done():
                        ready.set_result(True)
                    while True:
                        request = await queue.get()
                        if request.kind == "shutdown":
                            break
                        assert request.future is not None
                        try:
                            if request.kind == "list_tools":
                                outcome = await session.list_tools()
                            elif request.kind == "call_tool":
                                outcome = await session.call_tool(request.name or "", request.arguments or {})
                            elif request.kind == "ping":
                                outcome = await session.send_ping()
                            else:
                                raise ValueError(f"unknown request {request.kind}")
                            if not request.future.done():
                                request.future.set_result(outcome)
                        except Exception as exc:  # noqa: BLE001
                            wrapped = _classify(exc)
                            if not request.future.done():
                                request.future.set_exception(wrapped)
                            if isinstance(wrapped, MCPUnauthorized):
                                break
        except Exception as exc:  # noqa: BLE001
            log.warning("MCP session %s ended with error: %s", self.config.name, exc)
            if not ready.done():
                ready.set_exception(exc)
            # fail any queued requests
            while not queue.empty():
                pending = queue.get_nowait()
                if pending.future and not pending.future.done():
                    pending.future.set_exception(MCPConnectionError(str(exc)))
        finally:
            if not ready.done():
                ready.set_exception(MCPConnectionError("session closed before initialisation"))
            # Never leave callers waiting on a closed session (shutdown / unauthorized exit paths).
            while not queue.empty():
                pending = queue.get_nowait()
                if pending.future and not pending.future.done():
                    pending.future.set_exception(MCPConnectionError(f"{self.config.name} session closed"))


_UNAUTHORIZED = re.compile(
    r"(\b40[13]\b|unauthori[sz]ed|forbidden|invalid[_ ]token|token (has )?expired)", re.IGNORECASE
)


def is_unauthorized(exc: BaseException) -> bool:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status in (401, 403):
        return True
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, MCPUnauthorized) or _UNAUTHORIZED.search(str(current)):
            return True
        current = current.__cause__ or current.__context__
    return False


def _classify(exc: Exception) -> Exception:
    if is_unauthorized(exc):
        return MCPUnauthorized(str(exc))
    return exc
