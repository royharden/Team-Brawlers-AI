"""BudgetGuard — master plan §8.1 + §14 Phase 4 task 2.

Enforces the seven halt conditions named in the master plan:
    1. Per-run-type spend ceiling (smoke / seeded / exploratory).
    2. Daily cumulative spend ceiling.
    3. Cost-without-signal (N null attempts AND spent > threshold).
    4. Per-attack timeout.
    5. Target error rate over a rolling window.
    6. Operator halt (manual kill switch).

Once any condition triggers, :meth:`may_continue` returns ``False`` stickily
until a Phase-7 reset path lands (out of scope here).
"""

from __future__ import annotations

from collections import deque
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agentforge.config import BudgetConfig


class HaltReason(str, Enum):
    BUDGET_SMOKE_EXCEEDED = "budget_smoke_exceeded"
    BUDGET_SEEDED_EXCEEDED = "budget_seeded_exceeded"
    BUDGET_EXPLORATORY_EXCEEDED = "budget_exploratory_exceeded"
    BUDGET_PER_DAY_EXCEEDED = "budget_per_day_exceeded"
    COST_WITHOUT_SIGNAL = "cost_without_signal"
    PER_ATTACK_TIMEOUT = "per_attack_timeout"
    TARGET_ERROR_RATE_TOO_HIGH = "target_error_rate_too_high"
    OPERATOR_HALT = "operator_halt"


RunType = Literal["smoke", "seeded", "exploratory"]


_RUN_TYPE_HALT: dict[RunType, HaltReason] = {
    "smoke": HaltReason.BUDGET_SMOKE_EXCEEDED,
    "seeded": HaltReason.BUDGET_SEEDED_EXCEEDED,
    "exploratory": HaltReason.BUDGET_EXPLORATORY_EXCEEDED,
}


class BudgetState(BaseModel):
    """Snapshot of the current budget counters."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    spend_usd: Decimal = Decimal("0")
    spend_usd_today: Decimal = Decimal("0")
    attempts_since_last_finding: int = 0
    spend_since_last_finding_usd: Decimal = Decimal("0")
    target_error_count_in_window: int = 0
    target_request_count_in_window: int = 0
    halted: bool = False
    halt_reason: HaltReason | None = None
    run_type: RunType = "exploratory"
    operator_halt_note: str | None = None


_ERROR_WINDOW_SIZE = 50
_ERROR_WINDOW_MIN_REQUESTS = 20


class BudgetGuard:
    """Master plan §8.1 + §14 Phase 4 task 2.

    Halts the orchestrator when cost accumulates without producing signal,
    when a run-type or daily ceiling is breached, when a single attack
    exceeds the per-attack timeout, when the target's error rate spikes, or
    on an explicit operator halt.
    """

    def __init__(self, budget_config: BudgetConfig, run_type: RunType) -> None:
        self._cfg = budget_config
        self._run_type: RunType = run_type
        self._spend_usd: Decimal = Decimal("0")
        self._spend_usd_today: Decimal = Decimal("0")
        self._today: date = datetime.now(timezone.utc).date()
        self._attempts_since_last_finding: int = 0
        self._spend_since_last_finding_usd: Decimal = Decimal("0")
        # Rolling window of (was_error: bool) ticks.
        self._error_window: deque[bool] = deque(maxlen=_ERROR_WINDOW_SIZE)
        self._halt_reason: HaltReason | None = None
        self._operator_halt_note: str | None = None

    # ---------------------------------------------------------------- queries

    def may_continue(self) -> bool:
        """Idempotent. Returns False once any halt condition has fired."""
        # Recompute the per-day counter on day-rollover so a long-running run
        # that crosses UTC midnight does not stay artificially blocked.
        today = datetime.now(timezone.utc).date()
        if today != self._today:
            self._today = today
            self._spend_usd_today = Decimal("0")
        return self._halt_reason is None

    def halt_reason(self) -> HaltReason | None:
        return self._halt_reason

    def state(self) -> BudgetState:
        errors = sum(1 for e in self._error_window if e)
        requests = len(self._error_window)
        return BudgetState(
            spend_usd=self._spend_usd,
            spend_usd_today=self._spend_usd_today,
            attempts_since_last_finding=self._attempts_since_last_finding,
            spend_since_last_finding_usd=self._spend_since_last_finding_usd,
            target_error_count_in_window=errors,
            target_request_count_in_window=requests,
            halted=self._halt_reason is not None,
            halt_reason=self._halt_reason,
            run_type=self._run_type,
            operator_halt_note=self._operator_halt_note,
        )

    # ------------------------------------------------------------- mutations

    def tick_cost(self, cost_usd: Decimal) -> None:
        """Record incremental spend. Updates run / day ceiling + null-run state."""
        if self._halt_reason is not None:
            return
        # Roll the per-day bucket forward if needed.
        today = datetime.now(timezone.utc).date()
        if today != self._today:
            self._today = today
            self._spend_usd_today = Decimal("0")

        amount = cost_usd if isinstance(cost_usd, Decimal) else Decimal(str(cost_usd))
        self._spend_usd += amount
        self._spend_usd_today += amount
        self._attempts_since_last_finding += 1
        self._spend_since_last_finding_usd += amount

        # 1. Run-type ceiling.
        ceiling = _ceiling_for(self._cfg, self._run_type)
        if self._spend_usd > ceiling:
            self._halt(_RUN_TYPE_HALT[self._run_type])
            return

        # 2. Daily ceiling.
        if self._spend_usd_today > self._cfg.per_day_usd:
            self._halt(HaltReason.BUDGET_PER_DAY_EXCEEDED)
            return

        # 3. Cost-without-signal.
        if (
            self._attempts_since_last_finding >= self._cfg.halt_after_n_null_runs
            and self._spend_since_last_finding_usd > self._cfg.null_run_spend_threshold_usd
        ):
            self._halt(HaltReason.COST_WITHOUT_SIGNAL)
            return

    def tick_finding(self) -> None:
        """Reset the cost-without-signal counters."""
        if self._halt_reason is not None:
            return
        self._attempts_since_last_finding = 0
        self._spend_since_last_finding_usd = Decimal("0")

    def tick_target_error(self, *, was_error: bool) -> None:
        """Push one outcome onto the rolling error window and re-check."""
        if self._halt_reason is not None:
            return
        self._error_window.append(bool(was_error))
        requests = len(self._error_window)
        if requests < _ERROR_WINDOW_MIN_REQUESTS:
            return
        errors = sum(1 for e in self._error_window if e)
        rate = errors / requests
        if rate > self._cfg.target_error_rate_halt:
            self._halt(HaltReason.TARGET_ERROR_RATE_TOO_HIGH)

    def tick_per_attack_latency(self, latency_seconds: float) -> None:
        """A single attack exceeding the per-attack timeout halts the run."""
        if self._halt_reason is not None:
            return
        if latency_seconds > self._cfg.per_attack_timeout_s:
            self._halt(HaltReason.PER_ATTACK_TIMEOUT)

    def operator_halt(self, reason: str | None = None) -> None:
        """Manual kill switch. Always wins, even if a different halt reason
        was already set."""
        self._operator_halt_note = reason
        if self._halt_reason is None:
            self._halt_reason = HaltReason.OPERATOR_HALT

    # ----------------------------------------------------------------- utils

    def _halt(self, reason: HaltReason) -> None:
        # First halt reason wins; sticky.
        if self._halt_reason is None:
            self._halt_reason = reason


def _ceiling_for(cfg: BudgetConfig, run_type: RunType) -> Decimal:
    if run_type == "smoke":
        return cfg.smoke_usd
    if run_type == "seeded":
        return cfg.seeded_usd
    return cfg.exploratory_usd


__all__ = ["BudgetGuard", "BudgetState", "HaltReason", "RunType"]
