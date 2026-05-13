"""AttackStrategy ABC — master plan §8.2."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Strategy(ABC):
    """Base class for all attack strategies."""

    name: str = "base"

    @abstractmethod
    async def compose(self, seed: Any, context: dict[str, Any]) -> Any:
        """Compose an attack from a seed + context. Returns a MutatedAttack."""
