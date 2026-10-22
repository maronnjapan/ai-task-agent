"""LLM factory with provider adapters (SPEC 3.3, 4.5)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from app.infrastructure.secrets.base import SecretProvider
from app.infrastructure.secrets.bootstrap import secret_name_for_provider
from app.llm.configuration import LLMConfig

log = logging.getLogger(__name__)

ProviderFactory = Callable[[LLMConfig, str | None], BaseChatModel]


class LLMNotConfiguredError(RuntimeError):
    pass


def _openai(config: LLMConfig, api_key: str | None) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    if not api_key:
        raise LLMNotConfiguredError("OPENAI_API_KEY is not configured")
    kwargs: dict[str, Any] = {
        "model": config.model,
        "api_key": api_key,
        "timeout": config.timeout_seconds,
        "max_retries": config.max_retries,
    }
    if config.extra.get("base_url"):
        kwargs["base_url"] = config.extra["base_url"]
    if not str(config.model).startswith(("o1", "o3", "o4", "gpt-5", "gpt-6")) or config.extra.get(
        "force_temperature"
    ):
        kwargs["temperature"] = config.temperature
    return ChatOpenAI(**kwargs)


def _anthropic(config: LLMConfig, api_key: str | None) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    if not api_key:
        raise LLMNotConfiguredError("ANTHROPIC_API_KEY is not configured")
    return ChatAnthropic(
        model=config.model,
        api_key=api_key,
        temperature=config.temperature,
        timeout=config.timeout_seconds,
        max_retries=config.max_retries,
        max_tokens=int(config.extra.get("max_tokens", 8192)),
    )


def _google(config: LLMConfig, api_key: str | None) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    if not api_key:
        raise LLMNotConfiguredError("GOOGLE_API_KEY is not configured")
    return ChatGoogleGenerativeAI(
        model=config.model,
        google_api_key=api_key,
        temperature=config.temperature,
        timeout=config.timeout_seconds,
        max_retries=config.max_retries,
    )


def _fake(config: LLMConfig, api_key: str | None) -> BaseChatModel:
    from app.llm.fake import ScriptedChatModel

    return ScriptedChatModel(model_name=config.model)


class LLMFactory:
    """Creates chat models for the Manager / Worker / Review agents.

    Additional providers can be registered with :meth:`register_provider`
    (SPEC 3.3 "アダプターで追加したプロバイダー").
    """

    def __init__(self, secret_provider: SecretProvider, provider_override: str | None = None):
        self.secret_provider = secret_provider
        self.provider_override = provider_override
        self._providers: dict[str, ProviderFactory] = {
            "openai": _openai,
            "anthropic": _anthropic,
            "google": _google,
            "gemini": _google,
            "fake": _fake,
        }
        self._shared_models: dict[str, BaseChatModel] = {}

    def register_provider(self, name: str, factory: ProviderFactory) -> None:
        self._providers[name.lower()] = factory

    def providers(self) -> list[str]:
        return sorted(self._providers)

    def set_shared_model(self, agent: str, model: BaseChatModel) -> None:
        """Use one pre-built model instance for an agent (tests)."""
        self._shared_models[agent] = model

    def is_configured(self, provider: str) -> bool:
        provider = provider.lower()
        if provider == "fake" or provider not in ("openai", "anthropic", "google", "gemini"):
            return provider in self._providers
        return bool(self.secret_provider.get_secret(secret_name_for_provider(provider)))

    def create(self, config: LLMConfig) -> BaseChatModel:
        if config.agent in self._shared_models:
            return self._shared_models[config.agent]
        provider = (self.provider_override or config.provider or "openai").lower()
        factory = self._providers.get(provider)
        if factory is None:
            raise LLMNotConfiguredError(f"Unknown LLM provider: {provider}")
        api_key = None
        if provider not in ("fake",):
            api_key = self.secret_provider.get_secret(secret_name_for_provider(provider))
        log.debug("creating %s model for %s (%s)", provider, config.agent, config.model)
        return factory(config, api_key)
