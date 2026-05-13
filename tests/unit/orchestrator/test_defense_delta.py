"""DefenseDelta tests — master plan §4 / §12 / §14 Phase 6."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from agentforge.memory.models import DefenseDeltaSnapshot as _SnapshotRow
from agentforge.orchestrator.coverage import CoverageMatrix
from agentforge.orchestrator.defense_delta import DefenseDelta


@pytest.mark.unit
def test_snapshot_persists_to_db(
    session_factory: Callable[[], Session],
) -> None:
    """`DefenseDelta.snapshot(fingerprint)` writes a `defense_delta_snapshots` row with the per-cell pass rates JSON-encoded and an aggregate pass-rate (master plan §4 + §12)."""
    coverage = CoverageMatrix(session_factory)
    coverage.update("prompt_injection", "single_turn", outcome_passed=True)
    coverage.update("prompt_injection", "single_turn", outcome_passed=False)
    coverage.update("tool_misuse", "role_play", outcome_passed=True)
    dd = DefenseDelta(session_factory, coverage)
    snap = dd.snapshot("fp_abc")
    assert snap.target_fingerprint == "fp_abc"
    # 1 pass + 1 fail in PI + 1 pass in tool_misuse → aggregate 2/3.
    assert snap.aggregate_pass_rate == pytest.approx(2 / 3)
    assert snap.by_cell["prompt_injection:single_turn"] == pytest.approx(0.5)
    assert snap.by_cell["tool_misuse:role_play"] == pytest.approx(1.0)
    # And the row was persisted.
    session = session_factory()
    try:
        rows = session.query(_SnapshotRow).filter_by(fingerprint="fp_abc").all()
        assert len(rows) == 1
        stored = json.loads(rows[0].by_cell_json)
        assert "prompt_injection:single_turn" in stored
    finally:
        session.close()


@pytest.mark.unit
def test_trend_returns_most_recent_first(
    session_factory: Callable[[], Session],
) -> None:
    """`DefenseDelta.trend(last_n=N)` returns the N most-recent snapshots in descending `snapshot_at` order — drives the dashboard line graph."""
    coverage = CoverageMatrix(session_factory)
    coverage.update("prompt_injection", "single_turn", outcome_passed=True)
    dd = DefenseDelta(session_factory, coverage)
    dd.snapshot("fp_1")
    dd.snapshot("fp_2")
    dd.snapshot("fp_3")
    trend = dd.trend(last_n=2)
    assert len(trend) == 2
    # Most recent first.
    assert trend[0].target_fingerprint == "fp_3"
    assert trend[1].target_fingerprint == "fp_2"


@pytest.mark.unit
def test_delta_computes_b_minus_a(
    session_factory: Callable[[], Session],
) -> None:
    """`DefenseDelta.delta(fp_a, fp_b)` returns per-cell `(pass_rate_b - pass_rate_a)` — used by Phase-6 fix validation."""
    coverage = CoverageMatrix(session_factory)
    # Initial state: 1 fail in PI:single_turn → 0% pass rate.
    coverage.update("prompt_injection", "single_turn", outcome_passed=False)
    dd = DefenseDelta(session_factory, coverage)
    dd.snapshot("fp_before")
    # Simulate a fix: now passes.
    coverage.update("prompt_injection", "single_turn", outcome_passed=True)
    coverage.update("prompt_injection", "single_turn", outcome_passed=True)
    dd.snapshot("fp_after")
    delta = dd.delta("fp_before", "fp_after")
    # before: 0/1 = 0.0; after: 2/3 ≈ 0.6667 → diff ≈ 0.6667.
    assert delta["prompt_injection:single_turn"] == pytest.approx(2 / 3)


@pytest.mark.unit
def test_empty_coverage_yields_zero_aggregate(
    session_factory: Callable[[], Session],
) -> None:
    """Snapshotting with no coverage data returns `aggregate_pass_rate=0.0` and `by_cell={}` (no crash, no NaN)."""
    coverage = CoverageMatrix(session_factory)
    dd = DefenseDelta(session_factory, coverage)
    snap = dd.snapshot("fp_empty")
    assert snap.aggregate_pass_rate == 0.0
    assert snap.by_cell == {}
