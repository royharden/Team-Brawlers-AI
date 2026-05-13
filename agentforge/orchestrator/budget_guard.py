"""BudgetGuard — master plan §8.1 (four halt conditions)."""

from __future__ import annotations

from decimal import Decimal

from loguru import logger


class BudgetGuard:
    """Enforces budget ceilings + halts on signal-free spend.

    Halt conditions (master plan §8.1):
      1. Per-run-type spend ceiling exceeded (BUDGET_SMOKE_USD / _SEEDED_USD / _EXPLORATORY_USD).
      2. Daily spend ceiling exceeded (BUDGET_PER_DAY_USD).
      3. N consecutive null runs above signal threshold
         (BUDGET_HALT_AFTER_N_NULL_RUNS + BUDGET_NULL_RUN_SPEND_THRESHOLD_USD).
      4. Target error rate exceeds BUDGET_TARGET_ERROR_RATE_HALT.
    """

    def __init__(self) -> None:
        self._spent: Decimal = Decimal("0")
        self._null_run_streak: int = 0
        logger.debug("BudgetGuard stub init (Phase 0)")

    def may_continue(self) -> bool:
        """Return True if it's safe to spend more. Stub returns True."""
        return True

    def tick(self, cost_usd: Decimal) -> None:
        """Record incremental spend and update halt-condition state."""
        self._spent += cost_usd
