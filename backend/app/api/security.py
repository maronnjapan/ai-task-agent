"""Local API protection (SPEC 6.4): Host/Origin validation and CSRF header requirement."""

from __future__ import annotations

from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "AIWM"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def allowed_hosts(app_host: str, app_port: int) -> set[str]:
    hosts = {"127.0.0.1", "localhost", "[::1]", "::1", app_host}
    result = set()
    for host in hosts:
        if not host:
            continue
        result.add(host)
        result.add(f"{host}:{app_port}")
    return result


class LocalApiProtectionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, app_host: str, app_port: int, extra_hosts: set[str] | None = None):
        super().__init__(app)
        self.hosts = allowed_hosts(app_host, app_port) | (extra_hosts or set())
        # Binding to all interfaces (e.g. WSL reached from the Windows host) is an explicit
        # user choice; the Host check is relaxed but Origin and the CSRF header still apply.
        self.any_host = app_host in ("0.0.0.0", "::", "")

    def _host_ok(self, value: str | None) -> bool:
        if not value:
            return False
        if self.any_host:
            return True
        return value.lower() in {h.lower() for h in self.hosts} or value.split(":")[0].lower() in {
            h.split(":")[0].lower() for h in self.hosts
        }

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            host = request.headers.get("host")
            if not self._host_ok(host):
                return JSONResponse({"detail": "Invalid Host header"}, status_code=400)
            if request.method not in SAFE_METHODS:
                origin = request.headers.get("origin")
                if origin:
                    parsed = urlparse(origin)
                    same_host = parsed.netloc.lower() == (host or "").lower()
                    if not same_host and not (self._host_ok(parsed.netloc) and not self.any_host):
                        return JSONResponse(
                            {"detail": "Cross-origin requests are not allowed"}, status_code=403
                        )
                if request.headers.get(CSRF_HEADER, "").upper() != CSRF_VALUE:
                    return JSONResponse({"detail": f"Missing {CSRF_HEADER} header"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response
