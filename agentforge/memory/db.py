"""SQLAlchemy engine + sessionmaker — master plan §5.

Real implementation:
    - `engine` is a lazy singleton built from `PLATFORM_DB_URL`.
    - `SessionLocal` is the bound sessionmaker factory.
    - `get_session()` is the FastAPI dependency yielding a Session.
    - `init_db()` calls `Base.metadata.create_all(...)` for dev bootstrap.
      In production, Alembic migrations remain the source of truth.

SQLite-specific pragmas (`journal_mode=WAL`, `synchronous=NORMAL`) are wired
via a connection event listener — this matches the single-writer rule from
master plan §5.2 ("SQLite mode: WAL + synchronous=NORMAL").
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Generator
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from agentforge.config import get_settings
from agentforge.memory.models import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _enable_sqlite_pragmas(dbapi_conn: Any, _conn_record: Any) -> None:
    """Apply WAL + synchronous=NORMAL pragmas on SQLite connections."""
    try:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
    except Exception:
        pass


def make_engine(db_url: str | None = None) -> Engine:
    """Build a SQLAlchemy engine; ensures the SQLite parent dir exists."""
    url = db_url or get_settings().platform_db_url
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite"):
        # Allow cross-thread access (FastAPI + workers + tests).
        connect_args["check_same_thread"] = False
        _ensure_sqlite_parent_dir(url)
    engine = create_engine(url, future=True, connect_args=connect_args)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_pragmas)
    return engine


def _ensure_sqlite_parent_dir(url: str) -> None:
    """`sqlite:///./data/agentforge.sqlite` → ensure `./data/` exists."""
    # Strip scheme; SQLAlchemy supports both 3- and 4-slash forms.
    if url.startswith("sqlite:///"):
        path_str = url[len("sqlite:///") :]
    elif url.startswith("sqlite://"):
        path_str = url[len("sqlite://") :]
    else:
        return
    if not path_str or path_str == ":memory:":
        return
    p = Path(path_str)
    parent = p.parent
    if str(parent) and not parent.exists():
        with contextlib.suppress(OSError):
            parent.mkdir(parents=True, exist_ok=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a sessionmaker bound to `engine`."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_engine() -> Engine:
    """Lazy singleton accessor for the platform engine."""
    global _engine, _session_factory
    if _engine is None:
        _engine = make_engine()
        _session_factory = make_session_factory(_engine)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Lazy singleton accessor for the platform session factory."""
    global _session_factory
    if _session_factory is None:
        get_engine()  # initializes _session_factory as a side-effect
    assert _session_factory is not None
    return _session_factory


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency. Yields a Session; commits on success, rolls back on
    error, always closes."""
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(engine: Engine | None = None) -> None:
    """Create all tables for development bootstrap. Production runs `alembic
    upgrade head` instead — this is purely a "first-time setup" convenience.
    """
    eng = engine or get_engine()
    Base.metadata.create_all(bind=eng)


def reset_engine_for_tests() -> None:
    """Reset the lazy singletons. Used by tests to swap DB URLs."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
    # Also drop any cached settings — tests often monkeypatch env first.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        get_settings.cache_clear()
