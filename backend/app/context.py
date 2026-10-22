"""Application-wide context shared by API handlers, services and the orchestrator."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.config import Settings
from app.infrastructure.database import Database
from app.infrastructure.events import EventBroker
from app.infrastructure.paths import DataPaths
from app.infrastructure.secrets.base import InMemorySecretProvider, SecretProvider
from app.platform.base import PlatformAdapter

if TYPE_CHECKING:  # pragma: no cover
    from app.integrations.mcp.registry import MCPRegistry
    from app.llm.providers import LLMFactory
    from app.orchestrator.runner import Orchestrator


@dataclass
class AppContext:
    settings: Settings
    paths: DataPaths
    db: Database
    broker: EventBroker
    platform: PlatformAdapter
    secrets: InMemorySecretProvider  # API keys injected at bootstrap (memory only)
    secret_store: SecretProvider  # persistent store (Keychain / .env) for MCP credentials etc.
    llm_factory: LLMFactory | None = None
    mcp_registry: MCPRegistry | None = None
    orchestrator: Orchestrator | None = None
    started_at: float = field(default_factory=time.time)
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.started_at
