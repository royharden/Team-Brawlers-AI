"""Tree-of-attacks strategy — master plan §9.1 (uses treelib)."""

from __future__ import annotations

from typing import Any

from agentforge.redteam.strategies.base import Strategy


class TreeOfAttacksStrategy(Strategy):
    name = "tree_of_attacks"

    async def compose(self, seed: Any, context: dict[str, Any]) -> Any:
        raise NotImplementedError("Phase 2 — not yet wired")
