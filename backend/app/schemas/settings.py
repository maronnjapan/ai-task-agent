from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LLMAgentSettings(BaseModel):
    provider: str = "openai"
    model: str = "gpt-6"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    max_retries: int = Field(default=2, ge=0, le=10)
    custom_prompt: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class LLMSettings(BaseModel):
    manager: LLMAgentSettings = Field(default_factory=LLMAgentSettings)
    worker: LLMAgentSettings = Field(default_factory=LLMAgentSettings)
    review: LLMAgentSettings = Field(default_factory=LLMAgentSettings)


class ManagerSettingsOut(BaseModel):
    custom_prompt: str = ""
    autonomy_level: str = "balanced"
    reminder_aggressiveness: str = "normal"
    reevaluation_interval_minutes: int = 30
    max_replanning_attempts: int = 3
    max_worker_retries: int = 2
    max_consecutive_no_progress: int = 2


class NotificationSettings(BaseModel):
    level: str = "normal"  # low | normal | high
    desktop_enabled: bool = True
    quiet_hours_start: str | None = None  # "22:00"
    quiet_hours_end: str | None = None  # "07:00"
    min_interval_seconds: int = Field(default=60, ge=0)
    dedupe_window_minutes: int = Field(default=60, ge=0)
    pending_review_reminder_hours: int = Field(default=24, ge=0)


class LocalSourceSettings(BaseModel):
    directories: list[str] = Field(default_factory=list)
    extensions: list[str] = Field(
        default_factory=lambda: [".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".py", ".ts", ".js", ".go"]
    )
    max_file_size_kb: int = Field(default=512, ge=1)


class BackupSettings(BaseModel):
    directory: str | None = None
    auto_backup_interval_hours: int = Field(default=0, ge=0)  # 0 = disabled
    keep_last: int = Field(default=10, ge=1)


class ProviderKeyStatus(BaseModel):
    provider: str
    secret_name: str
    configured: bool
    backend: str


class SettingsOut(BaseModel):
    llm: LLMSettings
    manager: ManagerSettingsOut
    notifications: NotificationSettings
    local_sources: LocalSourceSettings
    backup: BackupSettings
    platform: dict[str, Any]
    secret_backend: str
    api_keys: list[ProviderKeyStatus]
    autostart_installed: bool
    data_directory: str
    env_file: str
    app: dict[str, Any]


class SettingsPatch(BaseModel):
    llm: LLMSettings | None = None
    manager: ManagerSettingsOut | None = None
    notifications: NotificationSettings | None = None
    local_sources: LocalSourceSettings | None = None
    backup: BackupSettings | None = None


class ApiKeyUpdate(BaseModel):
    provider: str
    api_key: str = Field(min_length=1)


class ApiKeyDelete(BaseModel):
    provider: str
