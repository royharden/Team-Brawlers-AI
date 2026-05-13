"""Shared fixtures for orchestrator unit tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from agentforge.memory.db import init_db, make_engine, make_session_factory


@pytest.fixture
def memory_engine() -> Engine:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return engine


@pytest.fixture
def session_factory(memory_engine: Engine) -> Callable[[], Session]:
    return make_session_factory(memory_engine)
