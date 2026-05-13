"""FastAPI dependency-injection helpers — master plan §4.

Two dependencies are exposed:

* ``get_session()`` — yields a SQLAlchemy ``Session`` bound to the platform
  engine. Wraps ``agentforge.memory.db.get_session`` so route handlers can
  ``Depends(get_session)`` without importing the memory module directly. Tests
  override this dependency via ``app.dependency_overrides`` to swap in an
  in-memory engine.
* ``get_settings_dep()`` — wraps ``agentforge.config.get_settings`` so the
  config singleton is overridable in tests.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from agentforge.config import MainConfig, get_settings
from agentforge.memory.db import get_session as _db_get_session


def get_session() -> Generator[Session, None, None]:
    """Yield a platform-DB Session. FastAPI consumes this as a dependency."""
    yield from _db_get_session()


def get_settings_dep() -> MainConfig:
    """Inject MainConfig singleton."""
    return get_settings()


# Backwards-compat alias for existing imports.
settings_dep = get_settings_dep


__all__ = ["get_session", "get_settings_dep", "settings_dep"]
