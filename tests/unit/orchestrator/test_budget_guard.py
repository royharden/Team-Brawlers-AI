"""BudgetGuard tests — master plan §8.1 + §14 Phase 4 task 2."""

from __future__ import annotations

from decimal import Decimal

import pytest

from agentforge.config import BudgetConfig
from agentforge.orchestrator.budget_guard import BudgetGuard, HaltReason


_ALIAS_BY_FIELD: dict[str, str] = {
    "smoke_usd": "BUDGET_SMOKE_USD",
    "seeded_usd": "BUDGET_SEEDED_USD",
    "exploratory_usd": "BUDGET_EXPLORATORY_USD",
    "per_day_usd": "BUDGET_PER_DAY_USD",
    "halt_after_n_null_runs": "BUDGET_HALT_AFTER_N_NULL_RUNS",
    "null_run_spend_threshold_usd": "BUDGET_NULL_RUN_SPEND_THRESHOLD_USD",
    "per_attack_timeout_s": "BUDGET_PER_ATTACK_TIMEOUT_S",
    "target_error_rate_halt": "BUDGET_TARGET_ERROR_RATE_HALT",
}


def _cfg(**overrides: object) -> BudgetConfig:
    """Build a BudgetConfig with sane defaults overridden for the test.

    Pydantic-Settings BudgetConfig uses field aliases (env-var names), so
    construction must go through the aliases.
    """
    defaults: dict[str, object] = {
        "smoke_usd": Decimal("1.00"),
        "seeded_usd": Decimal("5.00"),
        "exploratory_usd": Decimal("10.00"),
        "per_day_usd": Decimal("25.00"),
        "halt_after_n_null_runs": 25,
        "null_run_spend_threshold_usd": Decimal("3.00"),
        "per_attack_timeout_s": 60,
        "target_error_rate_halt": 0.20,
    }
    defaults.update(overrides)
    kwargs = {_ALIAS_BY_FIELD[k]: v for k, v in defaults.items()}
    return BudgetConfig(**kwargs)  # type: ignore[arg-type]


@pytest.mark.unit
def test_smoke_ceiling_triggers_halt() -> None:
    guard = BudgetGuard(_cfg(smoke_usd=Decimal("0.50")), run_type="smoke")
    guard.tick_cost(Decimal("0.40"))
    assert guard.may_continue()
    guard.tick_cost(Decimal("0.20"))  # cumulative 0.60 > 0.50
    assert not guard.may_continue()
    assert guard.halt_reason() == HaltReason.BUDGET_SMOKE_EXCEEDED


@pytest.mark.unit
def test_seeded_ceiling_triggers_halt() -> None:
    guard = BudgetGuard(_cfg(seeded_usd=Decimal("2.00")), run_type="seeded")
    guard.tick_cost(Decimal("2.10"))
    assert not guard.may_continue()
    assert guard.halt_reason() == HaltReason.BUDGET_SEEDED_EXCEEDED


@pytest.mark.unit
def test_exploratory_ceiling_triggers_halt() -> None:
    guard = BudgetGuard(_cfg(exploratory_usd=Decimal("1.00")), run_type="exploratory")
    guard.tick_cost(Decimal("1.50"))
    assert not guard.may_continue()
    assert guard.halt_reason() == HaltReason.BUDGET_EXPLORATORY_EXCEEDED


@pytest.mark.unit
def test_day_ceiling_triggers_halt() -> None:
    # Generous run-type ceilings so only the per-day ceiling can fire.
    cfg = _cfg(
        exploratory_usd=Decimal("1000.00"),
        per_day_usd=Decimal("2.00"),
    )
    guard = BudgetGuard(cfg, run_type="exploratory")
    guard.tick_cost(Decimal("1.50"))
    assert guard.may_continue()
    guard.tick_cost(Decimal("0.60"))  # cumulative 2.10 > 2.00
    assert not guard.may_continue()
    assert guard.halt_reason() == HaltReason.BUDGET_PER_DAY_EXCEEDED


@pytest.mark.unit
def test_cost_without_signal_triggers_halt() -> None:
    cfg = _cfg(
        halt_after_n_null_runs=3,
        null_run_spend_threshold_usd=Decimal("0.10"),
        # Big ceilings so the null-run path is the one that fires.
        exploratory_usd=Decimal("1000.00"),
        per_day_usd=Decimal("1000.00"),
    )
    guard = BudgetGuard(cfg, run_type="exploratory")
    guard.tick_cost(Decimal("0.05"))  # attempts=1, spent=0.05
    guard.tick_cost(Decimal("0.05"))  # attempts=2, spent=0.10 (not > threshold)
    assert guard.may_continue()
    guard.tick_cost(Decimal("0.05"))  # attempts=3, spent=0.15 > 0.10 AND attempts>=3
    assert not guard.may_continue()
    assert guard.halt_reason() == HaltReason.COST_WITHOUT_SIGNAL


@pytest.mark.unit
def test_per_attack_timeout_triggers_halt() -> None:
    guard = BudgetGuard(_cfg(per_attack_timeout_s=30), run_type="exploratory")
    guard.tick_per_attack_latency(29.5)
    assert guard.may_continue()
    guard.tick_per_attack_latency(31.0)
    assert not guard.may_continue()
    assert guard.halt_reason() == HaltReason.PER_ATTACK_TIMEOUT


@pytest.mark.unit
def test_target_error_rate_triggers_halt_above_threshold() -> None:
    # 30% error rate over 20 requests → above 0.20 threshold → halts.
    guard = BudgetGuard(_cfg(target_error_rate_halt=0.20), run_type="exploratory")
    for i in range(20):
        guard.tick_target_error(was_error=(i < 6))  # 6/20 = 0.30 > 0.20
    assert not guard.may_continue()
    assert guard.halt_reason() == HaltReason.TARGET_ERROR_RATE_TOO_HIGH


@pytest.mark.unit
def test_target_error_rate_does_not_halt_below_threshold() -> None:
    # 10% error rate over 20 requests → below 0.20 threshold → does not halt.
    guard = BudgetGuard(_cfg(target_error_rate_halt=0.20), run_type="exploratory")
    for i in range(20):
        guard.tick_target_error(was_error=(i < 2))  # 2/20 = 0.10
    assert guard.may_continue()
    # Also: with fewer than 20 requests, halt cannot fire even at 100% error.
    guard2 = BudgetGuard(_cfg(target_error_rate_halt=0.20), run_type="exploratory")
    for _ in range(10):
        guard2.tick_target_error(was_error=True)
    assert guard2.may_continue()


@pytest.mark.unit
def test_operator_halt_triggers_halt() -> None:
    guard = BudgetGuard(_cfg(), run_type="exploratory")
    guard.operator_halt("manual kill")
    assert not guard.may_continue()
    assert guard.halt_reason() == HaltReason.OPERATOR_HALT
    assert guard.state().operator_halt_note == "manual kill"


@pytest.mark.unit
def test_halt_is_sticky() -> None:
    """Once halted, may_continue stays False even after further tick calls."""
    guard = BudgetGuard(_cfg(smoke_usd=Decimal("0.10")), run_type="smoke")
    guard.tick_cost(Decimal("0.20"))
    assert not guard.may_continue()
    first_reason = guard.halt_reason()
    # Further ticks must NOT change the halt reason or unstick the halt.
    guard.tick_cost(Decimal("0.01"))
    guard.tick_target_error(was_error=False)
    guard.tick_finding()
    guard.tick_per_attack_latency(1.0)
    assert not guard.may_continue()
    assert guard.halt_reason() == first_reason


@pytest.mark.unit
def test_tick_finding_resets_counters() -> None:
    cfg = _cfg(
        halt_after_n_null_runs=3,
        null_run_spend_threshold_usd=Decimal("0.10"),
        exploratory_usd=Decimal("1000.00"),
        per_day_usd=Decimal("1000.00"),
    )
    guard = BudgetGuard(cfg, run_type="exploratory")
    guard.tick_cost(Decimal("0.05"))
    guard.tick_cost(Decimal("0.05"))
    guard.tick_finding()  # reset
    # Two more ticks (post-reset) should NOT trigger the halt now.
    guard.tick_cost(Decimal("0.05"))  # attempts_since_last_finding=1
    guard.tick_cost(Decimal("0.05"))  # attempts_since_last_finding=2 (< 3)
    assert guard.may_continue()
    state = guard.state()
    assert state.attempts_since_last_finding == 2
    assert state.spend_since_last_finding_usd == Decimal("0.10")
