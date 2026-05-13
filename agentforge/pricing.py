"""Pricing table loader — master plan §6, §15. Real impl deferred to Phase 1."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from loguru import logger


class PricingTable:
    """Loads config/pricing.yml; resolves USD cost per (provider, model, tokens)."""

    def __init__(self) -> None:
        self._table: dict[str, Any] = {}
        self._retrieved_on: str | None = None

    def load_from_yaml(self, path: Path) -> None:
        """Load pricing from a YAML file. Stub — Phase 1 wires this up."""
        logger.debug("PricingTable.load_from_yaml stub called for {}", path)
        raise NotImplementedError("Phase 1 — not yet wired")

    def cost_for_call(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> Decimal:
        """Compute USD cost for a single call. Stub — returns Decimal(0)."""
        logger.debug(
            "PricingTable.cost_for_call stub: {}/{} in={} out={}",
            provider,
            model,
            input_tokens,
            output_tokens,
        )
        return Decimal("0")

    def resolve_models(self) -> dict[str, str]:
        """Query provider models.list() at startup to resolve aliases. Stub."""
        raise NotImplementedError("Phase 1 — not yet wired")
