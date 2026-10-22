"""Session protection for the local API (SPEC 6.4 適切なセッション保護).

A random token is generated once per installation and kept in
``config/session.token`` (owner read/write only). The browser receives it
as an ``HttpOnly`` + ``SameSite=Strict`` cookie when it opens the app with
the tokenised URL printed by ``aiwm start`` (``?token=...``); command line
clients send it as the ``X-AIWM-Token`` header. Other local users cannot read
the file, and other sites cannot read or send the cookie.
"""

from __future__ import annotations

import hmac
import os
import secrets
import stat
from pathlib import Path

COOKIE_NAME = "aiwm_session"
HEADER_NAME = "x-aiwm-token"
QUERY_PARAM = "token"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30
EXEMPT_PATHS = ("/api/integrations/oauth/callback",)


def load_or_create_token(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = secrets.token_urlsafe(32)
    path.write_text(value, encoding="utf-8")
    if os.name != "nt":
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    return value


class SessionGuard:
    def __init__(self, token: str | None):
        self.token = token

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def matches(self, value: str | None) -> bool:
        return bool(self.token) and value is not None and hmac.compare_digest(value, self.token)

    def is_authorised(self, cookie: str | None, header: str | None) -> bool:
        if not self.enabled:
            return True
        return self.matches(cookie) or self.matches(header)

    @staticmethod
    def is_exempt(path: str) -> bool:
        return path.startswith(EXEMPT_PATHS)
