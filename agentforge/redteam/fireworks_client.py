"""Fireworks Dolphin client — placeholder per AgDR-0001 (substituted with Anthropic Sonnet).

Instantiation raises NotImplementedError. Future-proofs the swap: once a Fireworks
key lands, replace the body with an OpenAI-compatible chat client and set
REDTEAM_PROVIDER=fireworks.
"""

from __future__ import annotations

from typing import Any


class FireworksRedTeamClient:
    """Stub — refuses to instantiate when REDTEAM_PROVIDER=fireworks."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError(
            "Fireworks Dolphin substituted with Anthropic Sonnet — see AgDR-0001"
        )
