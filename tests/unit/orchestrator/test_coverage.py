"""CoverageMatrix tests — master plan §8.1 / Phase 4."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from agentforge.memory.models import CoverageCellRow
from agentforge.orchestrator.coverage import (
    CATEGORIES,
    STRATEGIES,
    CoverageMatrix,
)


@pytest.mark.unit
def test_update_creates_cell(session_factory: Callable[[], Session]) -> None:
    """A first update for a new (category, strategy) creates the row."""
    cm = CoverageMatrix(session_factory)
    cell = cm.update("prompt_injection", "single_turn", outcome_passed=True)
    assert cell.attempts == 1
    assert cell.passes == 1
    assert cell.failures == 0
    # And the row is persisted.
    session = session_factory()
    try:
        row = (
            session.query(CoverageCellRow)
            .filter_by(category="prompt_injection", strategy="single_turn")
            .one()
        )
        assert row.attempts == 1
        assert row.passes == 1
    finally:
        session.close()


@pytest.mark.unit
def test_update_increments_pass(session_factory: Callable[[], Session]) -> None:
    """Two passing outcomes for the same cell increment `passes` to 2 and yield `pass_rate=1.0`."""
    cm = CoverageMatrix(session_factory)
    cm.update("tool_misuse", "single_turn", outcome_passed=True)
    cell = cm.update("tool_misuse", "single_turn", outcome_passed=True)
    assert cell.attempts == 2
    assert cell.passes == 2
    assert cell.failures == 0
    assert cell.pass_rate == 1.0


@pytest.mark.unit
def test_update_increments_fail(session_factory: Callable[[], Session]) -> None:
    """One pass + one fail yields `passes=1`, `failures=1`, `pass_rate=0.5`."""
    cm = CoverageMatrix(session_factory)
    cm.update("data_exfiltration", "crescendo", outcome_passed=False)
    cell = cm.update("data_exfiltration", "crescendo", outcome_passed=True)
    assert cell.attempts == 2
    assert cell.passes == 1
    assert cell.failures == 1
    assert cell.pass_rate == 0.5


@pytest.mark.unit
def test_snapshot_returns_all_72_cells(
    session_factory: Callable[[], Session],
) -> None:
    """8 categories × 9 strategies = 72 cells regardless of DB state."""
    cm = CoverageMatrix(session_factory)
    # Populate two cells; the rest should still come back with zero counts.
    cm.update("clinical_integrity", "indirect_pdf", outcome_passed=False)
    cm.update("identity_role", "role_play", outcome_passed=True)
    snap = cm.snapshot()
    assert len(snap) == 72
    keys = {(c.category, c.strategy) for c in snap}
    assert keys == {(cat, strat) for cat in CATEGORIES for strat in STRATEGIES}
    # Untouched cells have zero counts.
    zero_cells = [c for c in snap if c.attempts == 0]
    assert len(zero_cells) == 70


@pytest.mark.unit
def test_uncovered_cells_filters_by_threshold(
    session_factory: Callable[[], Session],
) -> None:
    """`uncovered_cells(threshold_attempts=N)` returns cells with `attempts <= N`, sorted (category, strategy)."""
    cm = CoverageMatrix(session_factory)
    cm.update("prompt_injection", "single_turn", outcome_passed=True)
    cm.update("prompt_injection", "single_turn", outcome_passed=True)
    cm.update("tool_misuse", "single_turn", outcome_passed=True)  # attempts=1
    uncovered_zero = cm.uncovered_cells(threshold_attempts=0)
    assert all(c.attempts == 0 for c in uncovered_zero)
    assert len(uncovered_zero) == 70  # 72 - 2 touched cells

    uncovered_one = cm.uncovered_cells(threshold_attempts=1)
    # 70 zero-attempt cells + the tool_misuse cell with attempts=1
    assert len(uncovered_one) == 71
    # Sorted (category, strategy).
    cats = [c.category for c in uncovered_one]
    assert cats == sorted(cats)


@pytest.mark.unit
def test_degraded_cells_filter(session_factory: Callable[[], Session]) -> None:
    """Cells with last_attempt_at >= since AND last_pass_rate < 0.5 are flagged."""
    cm = CoverageMatrix(session_factory)
    # Two fails → pass_rate = 0.0 (degraded).
    cm.update("denial_of_service", "single_turn", outcome_passed=False)
    cm.update("denial_of_service", "single_turn", outcome_passed=False)
    # All passes — not degraded.
    cm.update("identity_role", "single_turn", outcome_passed=True)

    since = datetime.now(UTC) - timedelta(minutes=1)
    degraded = cm.degraded_cells(since)
    assert len(degraded) == 1
    assert degraded[0].category == "denial_of_service"
    assert degraded[0].strategy == "single_turn"

    # Looking forward in time → nothing degraded yet.
    future = datetime.now(UTC) + timedelta(minutes=1)
    assert cm.degraded_cells(future) == []
