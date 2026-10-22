"""Application settings.

General settings come from the ``.env`` file (or real environment variables).
Credentials are intentionally *not* part of :class:`Settings`; they are read
through the Secret Provider so that they never leak into logs or API responses.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_ROOT = Path(__file__).resolve().parent.parent


def locate_env_file() -> Path:
    """Return the ``.env`` path (``AIWM_ENV_FILE`` > cwd > project root)."""
    explicit = os.environ.get("AIWM_ENV_FILE")
    if explicit:
        return Path(explicit).expanduser()
    for candidate in (Path.cwd() / ".env", PROJECT_ROOT / ".env"):
        if candidate.exists():
            return candidate
    return PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(locate_env_file()),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_host: str = "127.0.0.1"
    app_port: int = 8765
    aiwm_data_dir: str | None = None

    default_llm_provider: str = "openai"
    manager_model: str = "gpt-6"
    worker_model: str = "gpt-6"
    review_model: str = "gpt-6"

    secret_backend: Literal["auto", "keychain", "dotenv"] = "auto"

    auto_start_manager: bool = True
    enable_desktop_notifications: bool = True

    log_level: str = "INFO"
    max_replanning_attempts: int = Field(default=3, ge=0)
    max_worker_retries: int = Field(default=2, ge=0)
    max_consecutive_no_progress: int = Field(default=2, ge=1)
    manager_reevaluation_interval_minutes: int = Field(default=30, ge=1)
    llm_timeout_seconds: int = Field(default=120, ge=1)
    llm_max_retries: int = Field(default=2, ge=0)

    # Testing / advanced
    aiwm_llm_provider_override: str | None = None
    aiwm_disable_orchestrator: bool = False

    @property
    def env_file(self) -> Path:
        return Path(self.model_config.get("env_file") or locate_env_file())

    def resolved_data_dir(self) -> Path:
        if self.aiwm_data_dir:
            return Path(self.aiwm_data_dir).expanduser()
        from app.platform import get_platform_adapter

        return get_platform_adapter().get_data_directory()


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
