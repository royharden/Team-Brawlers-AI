"""Cost tracker — master plan §12 (write-behind batched USD ledger). Stub."""

from __future__ import annotations

from decimal import Decimal


class CostTracker:
    """Token counter → USD via pricing.yml; batched insert into cost_ledger."""

    def __init__(self) -> None:
        self._buffer: list[tuple[str, str, int, int, Decimal]] = []

    def record(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: Decimal,
    ) -> None:
        self._buffer.append((provider, model, input_tokens, output_tokens, cost_usd))

    def flush(self) -> None:
        raise NotImplementedError("Phase 1 — not yet wired")
