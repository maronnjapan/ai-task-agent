"""SQLite engine / session management and schema initialisation (SPEC 23)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base

log = logging.getLogger(__name__)

FTS_DDL = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
        content, source, memory_id UNINDEXED, tokenize = 'trigram'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
        INSERT INTO memories_fts(rowid, content, source, memory_id)
        VALUES (new.rowid, new.content, coalesce(new.source, ''), new.id);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
        DELETE FROM memories_fts WHERE rowid = old.rowid;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
        DELETE FROM memories_fts WHERE rowid = old.rowid;
        INSERT INTO memories_fts(rowid, content, source, memory_id)
        VALUES (new.rowid, new.content, coalesce(new.source, ''), new.id);
    END
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS chat_messages_fts USING fts5(
        content, message_id UNINDEXED, chat_id UNINDEXED, tokenize = 'trigram'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chat_messages_ai AFTER INSERT ON chat_messages BEGIN
        INSERT INTO chat_messages_fts(rowid, content, message_id, chat_id)
        VALUES (new.rowid, new.content, new.id, new.chat_id);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chat_messages_ad AFTER DELETE ON chat_messages BEGIN
        DELETE FROM chat_messages_fts WHERE rowid = old.rowid;
    END
    """,
]

FTS_DROP = [
    "DROP TRIGGER IF EXISTS memories_ai",
    "DROP TRIGGER IF EXISTS memories_ad",
    "DROP TRIGGER IF EXISTS memories_au",
    "DROP TABLE IF EXISTS memories_fts",
    "DROP TRIGGER IF EXISTS chat_messages_ai",
    "DROP TRIGGER IF EXISTS chat_messages_ad",
    "DROP TABLE IF EXISTS chat_messages_fts",
]


def _apply_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.execute("PRAGMA busy_timeout = 5000")
    finally:
        cursor.close()


def make_engine(database_path: Path | str | None) -> Engine:
    """Create an engine; ``None`` means a shared in-memory database (tests)."""
    if database_path is None:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
    else:
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            f"sqlite+pysqlite:///{path}",
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_pre_ping=True,
            future=True,
        )
    event.listen(engine, "connect", _apply_pragmas)
    return engine


def create_fts(engine: Engine) -> None:
    with engine.begin() as conn:
        for ddl in FTS_DDL:
            conn.execute(text(ddl))


def create_schema(engine: Engine) -> None:
    """Create all tables directly (tests / fallback). Production uses Alembic."""
    Base.metadata.create_all(engine)
    create_fts(engine)


def run_migrations(engine: Engine) -> None:
    """Upgrade the database to the latest Alembic revision."""
    from alembic.config import Config

    from alembic import command

    backend_root = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.attributes["connection"] = None
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
    create_fts(engine)


class Database:
    def __init__(self, path: Path | None, use_migrations: bool = True):
        self.path = path
        self.use_migrations = use_migrations
        self.engine = make_engine(path)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.init_schema()

    def init_schema(self) -> None:
        if self.use_migrations and self.path is not None:
            run_migrations(self.engine)
        else:
            create_schema(self.engine)

    def reinitialize(self) -> None:
        """Re-open the database file (after a restore) and bring the schema up to date."""
        self.engine.dispose()
        self.init_schema()

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def new_session(self) -> Session:
        return self.session_factory()

    def dispose(self) -> None:
        self.engine.dispose()
