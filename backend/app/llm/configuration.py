"""Per-agent LLM configuration (SPEC 3.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.settings import LLMAgentSettings


@dataclass
class LLMConfig:
    agent: str  # manager | worker | review
    provider: str
    model: str
    temperature: float = 0.2
    timeout_seconds: int = 120
    max_retries: int = 2
    custom_prompt: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, agent: str, settings: LLMAgentSettings) -> LLMConfig:
        return cls(
            agent=agent,
            provider=(settings.provider or "openai").lower(),
            model=settings.model,
            temperature=settings.temperature,
            timeout_seconds=settings.timeout_seconds,
            max_retries=settings.max_retries,
            custom_prompt=settings.custom_prompt or "",
            extra=dict(settings.extra or {}),
        )
