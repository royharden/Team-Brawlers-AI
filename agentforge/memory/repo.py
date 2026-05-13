"""Repository pattern over `memory.models` — master plan §5. Stub."""

from __future__ import annotations

from typing import Any


class MemoryRepo:
    """Thin repository facade. Each Phase 1 method delegates to a SQLAlchemy session."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def save_run(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("Phase 1 — not yet wired")
