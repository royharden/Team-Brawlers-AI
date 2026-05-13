"""Langfuse client — master plan §12. No-op if keys absent."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from loguru import logger

from agentforge.config import get_settings

F = TypeVar("F", bound=Callable[..., Any])


class LangfuseClient:
    """Thin wrapper. Real client landed in Phase 1."""

    def __init__(self) -> None:
        cfg = get_settings().langfuse
        self._configured = cfg.is_configured
        if not self._configured:
            logger.debug("Langfuse keys not configured — operating in no-op mode")

    def trace(self, name: str) -> Callable[[F], F]:
        """Decorator that wraps a function in a Langfuse trace. No-op stub."""

        def decorator(fn: F) -> F:
            @wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                _ = name
                return fn(*args, **kwargs)

            return wrapper  # type: ignore[return-value]

        return decorator
