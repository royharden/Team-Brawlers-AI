"""Linear jailbreak strategy — master plan §9.1."""

from __future__ import annotations

from typing import Any

from agentforge.redteam.strategies.base import Strategy


class LinearJailbreakStrategy(Strategy):
    name = "linear_jailbreak"

    async def compose(self, seed: Any, context: dict[str, Any]) -> Any:
        raise NotImplementedError("Phase 2 — not yet wired")
