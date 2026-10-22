"""General application settings stored in SQLite (SPEC 4.1, 21)."""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AppSetting, ManagerSettings
from app.schemas.settings import (
    BackupSettings,
    LLMAgentSettings,
    LLMSettings,
    LocalSourceSettings,
    ManagerSettingsOut,
    NotificationSettings,
)
from app.utils import dumps, loads, now_iso

T = TypeVar("T", bound=BaseModel)


class SettingsService:
    def __init__(self, session: Session, settings: Settings):
        self.session = session
        self.settings = settings

    # --- generic key/value --------------------------------------------
    def get_raw(self, key: str, default: Any = None) -> Any:
        row = self.session.get(AppSetting, key)
        if row is None:
            return default
        return loads(row.value, default)

    def set_raw(self, key: str, value: Any) -> None:
        row = self.session.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value=dumps(value))
            self.session.add(row)
        else:
            row.value = dumps(value)
            row.updated_at = now_iso()
        self.session.flush()

    def _get_model(self, key: str, model: type[T], defaults: T) -> T:
        raw = self.get_raw(key)
        if not raw:
            return defaults
        merged = defaults.model_dump()
        merged.update(raw)
        return model.model_validate(merged)

    # --- typed sections ------------------------------------------------
    def llm_defaults(self) -> LLMSettings:
        s = self.settings

        def agent(model: str) -> LLMAgentSettings:
            return LLMAgentSettings(
                provider=s.default_llm_provider,
                model=model,
                timeout_seconds=s.llm_timeout_seconds,
                max_retries=s.llm_max_retries,
            )

        return LLMSettings(manager=agent(s.manager_model), worker=agent(s.worker_model), review=agent(s.review_model))

    def get_llm(self) -> LLMSettings:
        raw = self.get_raw("llm") or {}
        defaults = self.llm_defaults()
        data = defaults.model_dump()
        for agent_name in ("manager", "worker", "review"):
            if isinstance(raw.get(agent_name), dict):
                data[agent_name].update(raw[agent_name])
        return LLMSettings.model_validate(data)

    def set_llm(self, value: LLMSettings) -> None:
        self.set_raw("llm", value.model_dump())

    def get_manager(self) -> ManagerSettingsOut:
        row = self.session.get(ManagerSettings, "default")
        if row is None:
            row = ManagerSettings(id="default")
            self.session.add(row)
            self.session.flush()
        limits = self.get_raw("orchestrator") or {}
        return ManagerSettingsOut(
            custom_prompt=row.custom_prompt,
            autonomy_level=row.autonomy_level,
            reminder_aggressiveness=row.reminder_aggressiveness,
            reevaluation_interval_minutes=int(
                limits.get("reevaluation_interval_minutes", self.settings.manager_reevaluation_interval_minutes)
            ),
            max_replanning_attempts=int(limits.get("max_replanning_attempts", self.settings.max_replanning_attempts)),
            max_worker_retries=int(limits.get("max_worker_retries", self.settings.max_worker_retries)),
            max_consecutive_no_progress=int(
                limits.get("max_consecutive_no_progress", self.settings.max_consecutive_no_progress)
            ),
        )

    def set_manager(self, value: ManagerSettingsOut) -> None:
        row = self.session.get(ManagerSettings, "default")
        if row is None:
            row = ManagerSettings(id="default")
            self.session.add(row)
        row.custom_prompt = value.custom_prompt
        row.autonomy_level = value.autonomy_level
        row.reminder_aggressiveness = value.reminder_aggressiveness
        row.updated_at = now_iso()
        self.set_raw(
            "orchestrator",
            {
                "reevaluation_interval_minutes": value.reevaluation_interval_minutes,
                "max_replanning_attempts": value.max_replanning_attempts,
                "max_worker_retries": value.max_worker_retries,
                "max_consecutive_no_progress": value.max_consecutive_no_progress,
            },
        )
        self.session.flush()

    def get_notifications(self) -> NotificationSettings:
        defaults = NotificationSettings(desktop_enabled=self.settings.enable_desktop_notifications)
        return self._get_model("notifications", NotificationSettings, defaults)

    def set_notifications(self, value: NotificationSettings) -> None:
        self.set_raw("notifications", value.model_dump())

    def get_local_sources(self) -> LocalSourceSettings:
        return self._get_model("local_sources", LocalSourceSettings, LocalSourceSettings())

    def set_local_sources(self, value: LocalSourceSettings) -> None:
        self.set_raw("local_sources", value.model_dump())

    def get_backup(self) -> BackupSettings:
        return self._get_model("backup", BackupSettings, BackupSettings())

    def set_backup(self, value: BackupSettings) -> None:
        self.set_raw("backup", value.model_dump())

    def get_flag(self, key: str, default: bool = False) -> bool:
        return bool(self.get_raw(f"flag.{key}", default))

    def set_flag(self, key: str, value: bool) -> None:
        self.set_raw(f"flag.{key}", bool(value))
