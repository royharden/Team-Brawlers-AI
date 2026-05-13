"""Tests for shared dashboard helpers — master plan §12."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.engine import Engine

from agentforge.memory.db import init_db, make_engine, make_session_factory
from agentforge.memory.models import CostLedgerEntry, DefenseDeltaSnapshot, Run
from agentforge.observability.dashboards import (
    aggregate_run_costs,
    coverage_pct,
    recent_fingerprints,
)


@pytest.fixture
def engine() -> Engine:
    eng = make_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


@pytest.fixture
def session(engine):
    factory = make_session_factory(engine)
    s = factory()
    try:
        yield s
    finally:
        s.close()


@pytest.mark.unit
def test_aggregate_run_costs_rolls_up_by_role(session) -> None:
    """`aggregate_run_costs` returns total + n_calls + per-role Decimal sums (master plan §15)."""
    run = Run(
        id="r-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
        run_type="exploratory",
        status="done",
        total_cost_usd=Decimal("0"),
    )
    session.add(run)
    session.flush()
    rows = [
        CostLedgerEntry(
            id="c1",
            run_id="r-1",
            agent_role="red_team",
            provider="openrouter",
            model="dolphin",
            cost_usd=Decimal("0.10"),
        ),
        CostLedgerEntry(
            id="c2",
            run_id="r-1",
            agent_role="red_team",
            provider="openrouter",
            model="dolphin",
            cost_usd=Decimal("0.20"),
        ),
        CostLedgerEntry(
            id="c3",
            run_id="r-1",
            agent_role="external_judge",
            provider="anthropic",
            model="claude-sonnet-4-6",
            cost_usd=Decimal("0.50"),
        ),
    ]
    for r in rows:
        session.add(r)
    session.commit()

    agg = aggregate_run_costs(session)
    assert agg["n_calls"] == 3
    assert agg["total"] == Decimal("0.80")
    assert agg["by_role"]["red_team"] == Decimal("0.30")
    assert agg["by_role"]["external_judge"] == Decimal("0.50")


@pytest.mark.unit
def test_coverage_pct_handles_sparse_matrix() -> None:
    # Three covered cells out of 72.
    """`coverage_pct` denominator is always 72; sparse inputs treat missing cells as uncovered."""
    sparse = [
        {"attempts": 5},
        {"attempts": 0},
        {"attempts": 1},
        {"attempts": 2},
    ]
    pct = coverage_pct(sparse)
    # 3 covered cells over 72 total → ~4.16%.
    assert pytest.approx(pct, abs=0.01) == (3 / 72) * 100.0
    assert coverage_pct([]) == 0.0


@pytest.mark.unit
def test_recent_fingerprints_orders_distinct_most_recent_first(session) -> None:
    # Insert in order fp-old, fp-mid, fp-new with fp-mid duplicated.
    """`recent_fingerprints` returns distinct fingerprints ordered most-recent first (no duplicates from repeat snapshots)."""
    base = datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)
    rows = [
        DefenseDeltaSnapshot(
            fingerprint="fp-old",
            snapshot_at=base.replace(day=1),
            aggregate_pass_rate=0.0,
            by_cell_json=json.dumps({}),
        ),
        DefenseDeltaSnapshot(
            fingerprint="fp-mid",
            snapshot_at=base.replace(day=2),
            aggregate_pass_rate=0.0,
            by_cell_json=json.dumps({}),
        ),
        DefenseDeltaSnapshot(
            fingerprint="fp-mid",
            snapshot_at=base.replace(day=3),
            aggregate_pass_rate=0.0,
            by_cell_json=json.dumps({}),
        ),
        DefenseDeltaSnapshot(
            fingerprint="fp-new",
            snapshot_at=base.replace(day=4),
            aggregate_pass_rate=0.0,
            by_cell_json=json.dumps({}),
        ),
    ]
    for r in rows:
        session.add(r)
    session.commit()

    out = recent_fingerprints(session, limit=5)
    assert out == ["fp-new", "fp-mid", "fp-old"]
