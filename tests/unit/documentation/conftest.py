"""Shared fixtures for the Documentation Agent unit tests."""

from __future__ import annotations

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from agentforge.memory.db import init_db, make_engine, make_session_factory


@pytest.fixture
def memory_engine() -> Engine:
    """Fresh in-memory SQLite engine with FK enforcement enabled."""
    engine = make_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn: object, _record: object) -> None:
        cur = dbapi_conn.cursor()  # type: ignore[attr-defined]
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    init_db(engine)
    return engine


@pytest.fixture
def session_factory(memory_engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(memory_engine)
