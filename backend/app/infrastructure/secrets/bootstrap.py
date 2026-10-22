"""Startup bootstrap for credentials (SPEC 4.3-4.5).

1. Pick the Secret Provider from ``SECRET_BACKEND`` and the platform.
2. Check which LLM providers are configured.
3. Load their API keys; prompt interactively for missing keys when allowed.
4. Keep the keys in memory only and hand them to the LLM factory.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.infrastructure.logging import register_secret
from app.infrastructure.secrets.base import InMemorySecretProvider, LayeredSecretProvider, SecretProvider
from app.infrastructure.secrets.dotenv import DotEnvSecretProvider
from app.infrastructure.secrets.keychain import MacOSKeychainSecretProvider

log = logging.getLogger(__name__)

PROVIDER_SECRET_NAMES: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "gemini": "GOOGLE_API_KEY",
}


def secret_name_for_provider(provider: str) -> str:
    provider = provider.lower()
    if provider in PROVIDER_SECRET_NAMES:
        return PROVIDER_SECRET_NAMES[provider]
    return f"{provider.upper()}_API_KEY"


def select_secret_provider(backend: str, platform_name: str, env_file: Path) -> SecretProvider:
    """``auto``: macOS -> Keychain, Windows/WSL/Linux -> .env."""
    backend = (backend or "auto").lower()
    if backend == "auto":
        backend = "keychain" if platform_name == "macos" else "dotenv"
    if backend == "keychain":
        if platform_name != "macos":
            log.warning("SECRET_BACKEND=keychain is only supported on macOS; falling back to dotenv")
            return DotEnvSecretProvider(env_file)
        # Keychain first; .env as read-only fallback so a key placed there still works.
        return LayeredSecretProvider(MacOSKeychainSecretProvider(), DotEnvSecretProvider(env_file))
    if backend == "dotenv":
        return DotEnvSecretProvider(env_file)
    raise ValueError(f"Unsupported SECRET_BACKEND: {backend}")


Prompter = Callable[[str], str | None]
Confirmer = Callable[[str], bool]


@dataclass
class BootstrapResult:
    secrets: InMemorySecretProvider
    missing: list[str] = field(default_factory=list)
    stored: list[str] = field(default_factory=list)
    backend: str = ""


class SecretBootstrap:
    def __init__(
        self,
        provider: SecretProvider,
        prompter: Prompter | None = None,
        confirmer: Confirmer | None = None,
        interactive: bool = False,
    ):
        self.provider = provider
        self.prompter = prompter
        self.confirmer = confirmer
        self.interactive = interactive

    def run(self, required_providers: list[str]) -> BootstrapResult:
        result = BootstrapResult(secrets=InMemorySecretProvider(), backend=getattr(self.provider, "name", ""))
        seen: set[str] = set()
        for llm_provider in required_providers:
            secret_name = secret_name_for_provider(llm_provider)
            if secret_name in seen:
                continue
            seen.add(secret_name)
            value = self.provider.get_secret(secret_name)
            if not value and self.interactive and self.prompter is not None:
                value = self._prompt(llm_provider, secret_name)
                if value:
                    save = True
                    if self.confirmer is not None:
                        save = self.confirmer(secret_name)
                    if save:
                        self.provider.set_secret(secret_name, value)
                        result.stored.append(secret_name)
            if value:
                register_secret(value)
                result.secrets.set_secret(secret_name, value)
            else:
                result.missing.append(secret_name)
        return result

    def _prompt(self, llm_provider: str, secret_name: str) -> str | None:
        assert self.prompter is not None
        value = self.prompter(f"{llm_provider} API key ({secret_name})")
        value = (value or "").strip()
        return value or None


def console_prompter(label: str) -> str | None:
    import getpass

    print("AI Work Manager Setup")
    print()
    print(f"{label} is not configured.")
    print()
    try:
        return getpass.getpass("Please enter your API key: ")
    except (EOFError, KeyboardInterrupt):
        return None


def console_confirmer(backend_label: str) -> Confirmer:
    def _confirm(secret_name: str) -> bool:
        try:
            answer = input(f"Save this key to {backend_label}? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer in ("", "y", "yes")

    return _confirm
