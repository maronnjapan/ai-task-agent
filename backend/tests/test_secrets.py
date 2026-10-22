from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from app.infrastructure.logging import SecretRedactingFilter, redact, register_secret
from app.infrastructure.secrets.base import InMemorySecretProvider, LayeredSecretProvider
from app.infrastructure.secrets.bootstrap import (
    SecretBootstrap,
    secret_name_for_provider,
    select_secret_provider,
)
from app.infrastructure.secrets.dotenv import DotEnvSecretProvider
from app.infrastructure.secrets.keychain import MacOSKeychainSecretProvider


def test_dotenv_provider_roundtrip(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "APP_PORT=8765\nOPENAI_API_KEY=\n# comment\nexport ANTHROPIC_API_KEY='sk-ant-abc'\n", encoding="utf-8"
    )
    provider = DotEnvSecretProvider(env, env_fallback=False)
    assert provider.get_secret("OPENAI_API_KEY") is None
    assert provider.get_secret("ANTHROPIC_API_KEY") == "sk-ant-abc"
    provider.set_secret("OPENAI_API_KEY", "sk-test 123")
    provider.set_secret("GOOGLE_API_KEY", "AIza-x")
    text = env.read_text()
    assert (
        'OPENAI_API_KEY="sk-test 123"' in text and "GOOGLE_API_KEY=AIza-x" in text and "APP_PORT=8765" in text
    )
    assert provider.get_secret("OPENAI_API_KEY") == "sk-test 123"
    if os.name != "nt":
        assert stat.S_IMODE(env.stat().st_mode) == 0o600
    provider.delete_secret("GOOGLE_API_KEY")
    assert provider.get_secret("GOOGLE_API_KEY") is None and "GOOGLE_API_KEY=" in env.read_text()


def test_dotenv_env_fallback(tmp_path: Path, monkeypatch):
    provider = DotEnvSecretProvider(tmp_path / ".env")
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    assert provider.get_secret("OPENAI_API_KEY") == "from-env"


def test_keychain_provider_with_fake_security_cli():
    store: dict[str, str] = {}

    def runner(args, input_text=None):
        cmd = args[1]
        account = args[args.index("-a") + 1]
        if cmd == "find-generic-password":
            if account in store:
                return subprocess.CompletedProcess(args, 0, store[account] + "\n", "")
            return subprocess.CompletedProcess(args, 44, "", "The specified item could not be found")
        if cmd == "add-generic-password":
            store[account] = args[args.index("-w") + 1]
            return subprocess.CompletedProcess(args, 0, "", "")
        if cmd == "delete-generic-password":
            store.pop(account, None)
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(cmd)

    provider = MacOSKeychainSecretProvider(runner=runner)
    assert provider.get_secret("OPENAI_API_KEY") is None
    provider.set_secret("OPENAI_API_KEY", "sk-keychain")
    assert provider.get_secret("OPENAI_API_KEY") == "sk-keychain"
    provider.delete_secret("OPENAI_API_KEY")
    assert provider.get_secret("OPENAI_API_KEY") is None


def test_select_backend_auto(tmp_path: Path):
    env = tmp_path / ".env"
    assert isinstance(select_secret_provider("auto", "windows", env), DotEnvSecretProvider)
    assert isinstance(select_secret_provider("auto", "wsl", env), DotEnvSecretProvider)
    mac = select_secret_provider("auto", "macos", env)
    assert isinstance(mac, LayeredSecretProvider) and isinstance(mac.primary, MacOSKeychainSecretProvider)
    assert isinstance(select_secret_provider("keychain", "linux", env), DotEnvSecretProvider)
    with pytest.raises(ValueError):
        select_secret_provider("vault", "linux", env)


def test_bootstrap_prompts_and_stores_missing_keys():
    store = InMemorySecretProvider({"ANTHROPIC_API_KEY": "existing"})
    prompts: list[str] = []
    confirmations: list[str] = []

    def prompter(label: str) -> str:
        prompts.append(label)
        return "sk-entered"

    def confirmer(name: str) -> bool:
        confirmations.append(name)
        return True

    result = SecretBootstrap(store, prompter=prompter, confirmer=confirmer, interactive=True).run(
        ["openai", "anthropic", "gemini"]
    )
    assert result.secrets.get_secret("OPENAI_API_KEY") == "sk-entered"
    assert result.secrets.get_secret("ANTHROPIC_API_KEY") == "existing"
    assert store.get_secret("OPENAI_API_KEY") == "sk-entered"  # saved to the backend
    assert result.stored == ["OPENAI_API_KEY", "GOOGLE_API_KEY"] and result.missing == []
    assert prompts[0].startswith("openai")
    non_interactive = SecretBootstrap(InMemorySecretProvider(), interactive=False).run(["openai"])
    assert non_interactive.missing == ["OPENAI_API_KEY"]
    assert secret_name_for_provider("custom") == "CUSTOM_API_KEY"


def test_bootstrap_declined_save_keeps_key_in_memory_only():
    store = InMemorySecretProvider()
    result = SecretBootstrap(
        store, prompter=lambda _: "sk-temp", confirmer=lambda _: False, interactive=True
    ).run(["openai"])
    assert result.secrets.get_secret("OPENAI_API_KEY") == "sk-temp"
    assert store.get_secret("OPENAI_API_KEY") is None


def test_log_redaction():
    register_secret("sk-proj-SECRETVALUE123")
    assert "SECRETVALUE" not in redact("key sk-proj-SECRETVALUE123 used")
    assert redact("Authorization: Bearer abcdefghijklmnop") == "Authorization: ***"
    assert "***" in redact("api_key=abcdefgh")
    import logging

    record = logging.LogRecord("x", logging.INFO, "", 0, "token sk-ant-api03-abcdefghijklmnop", (), None)
    SecretRedactingFilter().filter(record)
    assert "abcdefghijklmnop" not in record.getMessage()
