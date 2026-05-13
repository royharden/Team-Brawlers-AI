"""FastAPI dependency-injection helpers — master plan §4."""

from __future__ import annotations

from agentforge.config import MainConfig, get_settings


def settings_dep() -> MainConfig:
    """Inject MainConfig singleton."""
    return get_settings()
