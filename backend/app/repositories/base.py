from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class Repository:
    """Small helper base: counting, paging and primary-key lookups."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, model: type[T], key: Any) -> T | None:
        return self.session.get(model, key)

    def count(self, stmt: Select) -> int:
        return int(self.session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())

    def page(self, stmt: Select, limit: int, offset: int) -> list[Any]:
        return list(self.session.execute(stmt.limit(limit).offset(offset)).scalars().all())

    def paginate(self, stmt: Select, limit: int, offset: int) -> tuple[list[Any], int]:
        return self.page(stmt, limit, offset), self.count(stmt)
