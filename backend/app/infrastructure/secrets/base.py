"""Secret Provider interface (SPEC 4.8)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SecretProvider(Protocol):
    name: str

    def get_secret(self, name: str) -> str | None: ...

    def set_secret(self, name: str, value: str) -> None: ...

    def delete_secret(self, name: str) -> None: ...


class InMemorySecretProvider:
    """Secrets held only in memory (used for tests and for injected keys)."""

    name = "memory"

    def __init__(self, initial: dict[str, str] | None = None):
        self._values: dict[str, str] = dict(initial or {})

    def get_secret(self, name: str) -> str | None:
        return self._values.get(name) or None

    def set_secret(self, name: str, value: str) -> None:
        self._values[name] = value

    def delete_secret(self, name: str) -> None:
        self._values.pop(name, None)

    def names(self) -> list[str]:
        return sorted(self._values)


class LayeredSecretProvider:
    """Reads from the first provider that has the value; writes to the primary."""

    name = "layered"

    def __init__(self, primary: SecretProvider, *fallbacks: SecretProvider):
        self.primary = primary
        self.fallbacks = list(fallbacks)

    def get_secret(self, name: str) -> str | None:
        for provider in (self.primary, *self.fallbacks):
            value = provider.get_secret(name)
            if value:
                return value
        return None

    def set_secret(self, name: str, value: str) -> None:
        self.primary.set_secret(name, value)

    def delete_secret(self, name: str) -> None:
        for provider in (self.primary, *self.fallbacks):
            provider.delete_secret(name)
