"""Target adapter ABC + AdapterResponse — master plan §4."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class AdapterResponse(BaseModel):
    """Normalized response envelope returned by every TargetAdapter."""

    status_code: int
    headers: dict[str, str] = Field(default_factory=dict)
    body_text: str = ""
    body_json: dict[str, Any] | None = None
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    error: str | None = None


class TargetAdapter(ABC):
    """Base class for all target adapters."""

    name: str = "base"

    @abstractmethod
    async def execute(self, attack: Any) -> AdapterResponse:
        """Dispatch the attack to the target and normalize the response."""

    @abstractmethod
    def describe_action(self, attack: Any) -> str:
        """Return a one-line human description of what this adapter would do."""
