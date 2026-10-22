"""Transport factories: stdio and Streamable HTTP (SPEC 17.2, 17.4, 17.5)."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.integrations.mcp.config import ConnectionConfig


def resolve_command(command: str) -> str:
    """Resolve the executable per OS (``npx`` -> ``npx.cmd`` on Windows, PATH lookup, ``~`` expansion)."""
    expanded = os.path.expandvars(os.path.expanduser(command))
    if os.path.isabs(expanded) or os.sep in expanded:
        return expanded
    found = shutil.which(expanded)
    if found:
        return found
    if sys.platform == "win32":  # pragma: no cover - Windows only
        for suffix in (".cmd", ".exe", ".bat"):
            found = shutil.which(expanded + suffix)
            if found:
                return found
    return expanded


@asynccontextmanager
async def open_transport(config: ConnectionConfig, headers: dict[str, str] | None = None) -> AsyncIterator[tuple[Any, Any]]:
    """Yield ``(read_stream, write_stream)`` for the configured transport."""
    if config.transport == "stdio":
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        if not config.command:
            raise ValueError("stdio transport requires a command")
        params = StdioServerParameters(command=resolve_command(config.command), args=list(config.args), env={**os.environ, **config.env} if config.env else None)
        async with stdio_client(params) as streams:
            yield streams[0], streams[1]
        return
    if config.transport == "streamable_http":
        import httpx2
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

        if not config.url:
            raise ValueError("streamable_http transport requires a url")
        merged = {**config.headers, **(headers or {})}
        timeout = httpx2.Timeout(float(config.timeout_seconds), read=max(60.0, float(config.timeout_seconds) * 10))
        async with create_mcp_http_client(headers=merged, timeout=timeout) as client:
            async with streamable_http_client(config.url, http_client=client) as streams:
                yield streams[0], streams[1]
        return
    raise ValueError(f"Unsupported transport: {config.transport}")
