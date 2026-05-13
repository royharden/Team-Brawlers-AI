"""Notifier — master plan §12. Multi-channel config in config/notifier.yml. Stub."""

from __future__ import annotations

from typing import Any


class Notifier:
    """In-app notifications + optional Slack/email channels."""

    def __init__(self) -> None:
        self._channels: list[Any] = []

    def high_sev_finding(self, vr: Any) -> None:
        """Send a high-severity notification. Stub."""
        raise NotImplementedError("Phase 3 — not yet wired")
