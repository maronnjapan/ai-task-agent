"""Tiny MCP server used by the integration tests (stdio and Streamable HTTP)."""

from __future__ import annotations

import os
import sys

from mcp.server.mcpserver import MCPServer

server = MCPServer(name="aiwm-test-server", instructions="Test server for AI Work Manager")


@server.tool(name="search_messages", description="Search fake messages")
def search_messages(query: str, count: int = 10) -> dict:
    return {
        "messages": [
            {
                "text": f"result for {query} #{i}",
                "permalink": f"https://example.test/{i}",
                "channel": {"name": "general"},
                "user": "alice",
            }
            for i in range(min(count, 3))
        ]
    }


@server.tool(name="get_item", description="Read one item")
def get_item(item_id: str) -> str:
    return f"item {item_id}: hello from the MCP test server"


@server.tool(name="post_message", description="Post a message (external write)")
def post_message(channel: str, text: str) -> str:
    return f"posted to {channel}: {text}"


@server.tool(name="fail", description="Always fails")
def fail() -> str:
    raise ValueError("tool failure for tests")


def build_http_app(expected_bearer: str | None = None):
    """Starlette app wrapping the server; optionally enforces a bearer token."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    app = server.streamable_http_app(stateless_http=True, json_response=True)
    if expected_bearer:

        class AuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                if request.headers.get("authorization") != f"Bearer {expected_bearer}":
                    return JSONResponse({"error": "unauthorized"}, status_code=401)
                return await call_next(request)

        app.add_middleware(AuthMiddleware)
    return app


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "http":
        import uvicorn

        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8900
        uvicorn.run(
            build_http_app(os.environ.get("AIWM_TEST_BEARER")),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    else:
        server.run("stdio")
