"""Cost-threshold detectors (denial_of_service rubrics) — master plan §8.3. Stub."""

from __future__ import annotations

from decimal import Decimal

MAX_LATENCY_S: float = 30.0
MAX_TOKENS: int = 4096
MAX_COST_PER_REQUEST_USD: Decimal = Decimal("0.10")
MAX_CHILD_API_CALLS: int = 2
