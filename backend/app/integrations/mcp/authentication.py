"""Authentication strategies for MCP servers (SPEC 17.6).

Supported: none, api_token (custom header), bearer, oauth2 (authorization code
with refresh) and custom (adapter-provided). Secrets live in the Secret
Provider, never in SQLite.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlencode

from app.infrastructure.secrets.base import SecretProvider
from app.integrations.mcp.config import ConnectionConfig

log = logging.getLogger(__name__)


class AuthStrategy(Protocol):
    auth_type: str

    async def headers(self) -> dict[str, str]: ...

    async def on_unauthorized(self) -> bool:
        """Try to recover (e.g. refresh a token). Return True if the request can be retried."""
        ...

    def is_ready(self) -> bool: ...


class NoAuth:
    auth_type = "none"

    async def headers(self) -> dict[str, str]:
        return {}

    async def on_unauthorized(self) -> bool:
        return False

    def is_ready(self) -> bool:
        return True


class ApiTokenAuth:
    auth_type = "api_token"

    def __init__(self, token: str | None, header_name: str = "X-API-Key", prefix: str = ""):
        self.token = token
        self.header_name = header_name
        self.prefix = prefix

    async def headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {self.header_name: f"{self.prefix}{self.token}"}

    async def on_unauthorized(self) -> bool:
        return False

    def is_ready(self) -> bool:
        return bool(self.token)


class BearerAuth(ApiTokenAuth):
    auth_type = "bearer"

    def __init__(self, token: str | None):
        super().__init__(token, header_name="Authorization", prefix="Bearer ")


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None
    token_type: str = "Bearer"
    scope: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def expired(self, leeway: float = 60.0) -> bool:
        return self.expires_at is not None and time.time() >= self.expires_at - leeway

    def to_json(self) -> str:
        return json.dumps(self.__dict__)

    @classmethod
    def from_json(cls, text: str | None) -> OAuthTokens | None:
        if not text:
            return None
        try:
            data = json.loads(text)
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (ValueError, TypeError):
            return None

    @classmethod
    def from_response(cls, data: dict[str, Any], previous: OAuthTokens | None = None) -> OAuthTokens:
        expires_in = data.get("expires_in")
        expires_at = time.time() + float(expires_in) if expires_in else None
        return cls(
            access_token=str(data["access_token"]),
            refresh_token=data.get("refresh_token") or (previous.refresh_token if previous else None),
            expires_at=expires_at,
            token_type=data.get("token_type", "Bearer"),
            scope=data.get("scope"),
        )


HttpPost = Callable[[str, dict[str, str], dict[str, str]], Any]


async def default_http_post(url: str, data: dict[str, str], headers: dict[str, str]) -> dict[str, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, data=data, headers=headers)
        if response.status_code >= 400:
            raise OAuthError(f"token endpoint returned {response.status_code}: {response.text[:300]}")
        return response.json()


class OAuthError(RuntimeError):
    pass


class OAuth2Auth:
    """Authorization-code flow with PKCE and refresh (SPEC 17.6)."""

    auth_type = "oauth2"

    def __init__(self, config: ConnectionConfig, secret_store: SecretProvider, http_post: HttpPost | None = None):
        self.config = config
        self.secret_store = secret_store
        self.http_post = http_post or default_http_post
        self.settings = config.auth_config
        self.secret_name = config.oauth_secret_name()
        self._tokens: OAuthTokens | None = OAuthTokens.from_json(secret_store.get_secret(self.secret_name))

    # --- settings ---------------------------------------------------
    @property
    def client_id(self) -> str:
        return str(self.settings.get("client_id", ""))

    @property
    def client_secret(self) -> str | None:
        return self.secret_store.get_secret(self.config.secret_name())

    @property
    def redirect_uri(self) -> str:
        return str(self.settings.get("redirect_uri", "http://127.0.0.1:8765/api/integrations/oauth/callback"))

    # --- flow -------------------------------------------------------
    def authorization_url(self, state: str, code_verifier: str | None = None) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        if self.settings.get("scope"):
            params["scope"] = str(self.settings["scope"])
        if code_verifier:
            challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
            params["code_challenge"] = challenge
            params["code_challenge_method"] = "S256"
        for key, value in (self.settings.get("extra_authorize_params") or {}).items():
            params[str(key)] = str(value)
        return f"{self.settings['authorization_url']}?{urlencode(params)}"

    async def exchange_code(self, code: str, code_verifier: str | None = None) -> OAuthTokens:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        headers = {"Accept": "application/json"}
        secret = self.client_secret
        if secret:
            data["client_secret"] = secret
        response = await self.http_post(str(self.settings["token_url"]), data, headers)
        if "access_token" not in response:
            raise OAuthError(f"token response has no access_token: {list(response)}")
        self._tokens = OAuthTokens.from_response(response)
        self.secret_store.set_secret(self.secret_name, self._tokens.to_json())
        return self._tokens

    async def refresh(self) -> OAuthTokens:
        if not self._tokens or not self._tokens.refresh_token:
            raise OAuthError("no refresh token available; re-authentication required")
        data = {"grant_type": "refresh_token", "refresh_token": self._tokens.refresh_token, "client_id": self.client_id}
        secret = self.client_secret
        if secret:
            data["client_secret"] = secret
        response = await self.http_post(str(self.settings["token_url"]), data, {"Accept": "application/json"})
        if "access_token" not in response:
            raise OAuthError("refresh failed")
        self._tokens = OAuthTokens.from_response(response, previous=self._tokens)
        self.secret_store.set_secret(self.secret_name, self._tokens.to_json())
        return self._tokens

    def revoke_local(self) -> None:
        self._tokens = None
        self.secret_store.delete_secret(self.secret_name)

    # --- AuthStrategy -----------------------------------------------
    async def headers(self) -> dict[str, str]:
        if self._tokens is None:
            return {}
        if self._tokens.expired():
            await self.refresh()
        return {"Authorization": f"{self._tokens.token_type or 'Bearer'} {self._tokens.access_token}"}

    async def on_unauthorized(self) -> bool:
        try:
            await self.refresh()
            return True
        except OAuthError as exc:
            log.warning("OAuth refresh failed for %s: %s", self.config.name, exc)
            return False

    def is_ready(self) -> bool:
        return self._tokens is not None

    @property
    def tokens(self) -> OAuthTokens | None:
        return self._tokens


@dataclass
class PendingAuthorization:
    connection_id: str
    state: str
    code_verifier: str
    created_at: float = field(default_factory=time.time)


class OAuthFlowManager:
    """Keeps in-flight authorization states (SPEC 17.6: 認可URLへの遷移 / Callback処理)."""

    def __init__(self, ttl_seconds: int = 900):
        self._pending: dict[str, PendingAuthorization] = {}
        self.ttl = ttl_seconds

    def begin(self, connection_id: str) -> PendingAuthorization:
        self._cleanup()
        pending = PendingAuthorization(connection_id=connection_id, state=secrets.token_urlsafe(24), code_verifier=secrets.token_urlsafe(48))
        self._pending[pending.state] = pending
        return pending

    def take(self, state: str) -> PendingAuthorization | None:
        self._cleanup()
        return self._pending.pop(state, None)

    def _cleanup(self) -> None:
        now = time.time()
        for key in [k for k, v in self._pending.items() if now - v.created_at > self.ttl]:
            self._pending.pop(key, None)


def build_auth(config: ConnectionConfig, secret_store: SecretProvider, http_post: HttpPost | None = None) -> AuthStrategy:
    auth_type = (config.auth_type or "none").lower()
    if auth_type == "none":
        return NoAuth()
    if auth_type == "api_token":
        return ApiTokenAuth(
            secret_store.get_secret(config.secret_name()),
            header_name=str(config.auth_config.get("header_name", "X-API-Key")),
            prefix=str(config.auth_config.get("prefix", "")),
        )
    if auth_type == "bearer":
        return BearerAuth(secret_store.get_secret(config.secret_name()))
    if auth_type == "oauth2":
        return OAuth2Auth(config, secret_store, http_post=http_post)
    if auth_type == "custom":
        from app.integrations.mcp.adapters import get_adapter

        adapter = get_adapter(config.adapter)
        custom = adapter.custom_auth(config, secret_store)
        return custom or NoAuth()
    raise ValueError(f"Unsupported auth_type: {auth_type}")
