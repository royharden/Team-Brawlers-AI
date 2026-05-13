"""Target allowlist — master plan §4 + AgDR-0002 (local-only).

Real implementation. Hard safety boundary: every adapter must call `is_allowed`
before any outbound request. `TargetNotAllowed` MUST propagate (never caught
silently).
"""

from __future__ import annotations

from urllib.parse import urlparse

from agentforge.config import MainConfig, get_settings


class TargetNotAllowed(Exception):
    """Raised when an out-of-scope host is targeted."""


def is_allowed(url: str, settings: MainConfig | None = None) -> bool:
    """Return True iff `url`'s host is on TARGET_ALLOWLIST.

    Empty URL, malformed URL, missing host, or unknown scheme → False.
    """
    if not url or not isinstance(url, str):
        return False

    cfg = settings if settings is not None else get_settings()
    allowlist = {h.lower() for h in cfg.adapter.target_allowlist}

    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    host = (parsed.hostname or "").lower()
    if not host:
        return False
    return host in allowlist


def require_allowed(url: str, settings: MainConfig | None = None) -> None:
    """Raise `TargetNotAllowed` if `url` is not on the allowlist."""
    if not is_allowed(url, settings=settings):
        raise TargetNotAllowed(f"Host for URL {url!r} is not on TARGET_ALLOWLIST")
