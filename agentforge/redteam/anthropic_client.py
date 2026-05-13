"""Red Team Anthropic client — master plan §8.2 + AgDR-0001.

This is the ONLY module under agentforge/redteam/ that imports the `anthropic` SDK.
A CI lint (tests/unit/redteam/test_provider_isolation.py) will enforce that invariant
in Phase 2.
"""

from __future__ import annotations

from typing import Any

import anthropic  # noqa: F401  # AgDR-0001 — sanctioned import location

from loguru import logger


class RedTeamAnthropicClient:
    """Thin wrapper around `anthropic.Anthropic` for Red Team calls."""

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        logger.debug("RedTeamAnthropicClient stub init (model={})", model)

    async def chat(self, *args: Any, **kwargs: Any) -> Any:
        """Issue a chat completion via the Anthropic SDK. Stub — Phase 2."""
        raise NotImplementedError("Phase 2 — not yet wired")
