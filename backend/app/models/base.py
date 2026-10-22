from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.utils import new_id, now_iso


class Base(DeclarativeBase):
    pass


def id_column() -> Mapped[str]:
    return mapped_column(String, primary_key=True, default=new_id)


def ts_column(nullable: bool = False) -> Mapped[str]:
    return mapped_column(String, nullable=nullable, default=now_iso)
