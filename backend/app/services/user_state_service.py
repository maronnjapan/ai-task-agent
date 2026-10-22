"""User condition tracking (SPEC 19)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import UserState
from app.services.audit_service import AuditService
from app.utils import iso_in, now_iso, parse_iso, utcnow


class UserStateService:
    def __init__(self, session: Session):
        self.session = session

    def get(self) -> UserState:
        state = self.session.get(UserState, "current")
        if state is None:
            state = UserState(id="current", condition="", source="user")
            self.session.add(state)
            self.session.flush()
        return state

    def is_active(self, state: UserState) -> bool:
        if not state.condition:
            return False
        expires = parse_iso(state.expires_at)
        return expires is None or expires > utcnow()

    def current_condition(self) -> str | None:
        state = self.get()
        return state.condition if self.is_active(state) else None

    def set(
        self, condition: str, source: str = "user", expires_in_minutes: int | None = None, actor: str = "user"
    ) -> UserState:
        state = self.get()
        # An explicit user statement always wins over an AI estimate.
        if source != "user" and state.source == "user" and self.is_active(state):
            return state
        state.condition = condition.strip()
        state.source = source
        state.expires_at = (
            iso_in(minutes=expires_in_minutes)
            if expires_in_minutes
            else (iso_in(hours=4) if source != "user" else None)
        )
        state.updated_at = now_iso()
        self.session.flush()
        AuditService(self.session).record(
            "user_state.updated", "user_state", "current", actor, {"condition": condition, "source": source}
        )
        return state

    def clear(self) -> UserState:
        state = self.get()
        state.condition = ""
        state.source = "user"
        state.expires_at = None
        state.updated_at = now_iso()
        self.session.flush()
        return state
