"""SQLAlchemy engine + sessionmaker — master plan §5."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from agentforge.config import get_settings


def make_engine(db_url: str | None = None) -> Engine:
    """Build a SQLAlchemy engine. SQLite WAL is set in Phase 1."""
    url = db_url or get_settings().platform_db_url
    return create_engine(url, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a sessionmaker bound to `engine`."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def create_all_stub() -> None:
    """Helper to create all tables. Real impl deferred to Alembic in Phase 1."""
    raise NotImplementedError("Phase 1 — use `alembic upgrade head` instead")
