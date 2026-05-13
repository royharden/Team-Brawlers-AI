"""Shared fixtures for FastAPI route tests — master plan §4 + §13.

Each test gets a brand-new in-memory SQLite engine wired through
``app.dependency_overrides`` so route handlers see a clean DB but the rest of
the platform's session-factory stays untouched.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agentforge.api.deps import get_session
from agentforge.api.main import app
from agentforge.memory.db import init_db, make_session_factory
from agentforge.memory.models import (
    AttackJob,
    AttackTrace,
    CostLedgerEntry,
    CoverageCellRow,
    DefenseDeltaSnapshot,
    RegressionCase,
    Run,
    Verdict,
    VulnReport,
)


@pytest.fixture
def api_engine() -> Engine:
    # Shared in-memory SQLite — StaticPool keeps every connection on the same
    # underlying DB so the seeding session, the route handler session, and the
    # assertion-time session all see the same rows.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    init_db(engine)
    return engine


@pytest.fixture
def api_session_factory(api_engine: Engine):
    return make_session_factory(api_engine)


@pytest.fixture
def client(api_session_factory) -> Iterator[TestClient]:
    """TestClient whose `get_session` dep returns sessions from the in-memory
    engine. Cleared on teardown so no test bleeds dependencies.
    """

    def _override() -> Generator[Session, None, None]:
        session: Session = api_session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def seeded_session(api_session_factory) -> Iterator[Session]:
    """Open a session, hand it back to the caller for seeding, commit on exit."""
    s: Session = api_session_factory()
    try:
        yield s
        s.commit()
    finally:
        s.close()


# --- helpers reusable across the api/ test files ---------------------------


def seed_run(session: Session, run_id: str = "run-1", status: str = "running") -> Run:
    r = Run(
        id=run_id,
        started_at=datetime.now(timezone.utc).replace(tzinfo=None),
        run_type="exploratory",
        status=status,
        total_cost_usd=Decimal("0"),
    )
    session.add(r)
    session.flush()
    return r


def seed_attack(
    session: Session,
    run_id: str = "run-1",
    job_id: str = "job-1",
    trace_id: str = "trace-1",
    category: str = "prompt_injection",
    strategy: str = "single_turn",
) -> tuple[AttackJob, AttackTrace]:
    job = AttackJob(
        id=job_id,
        run_id=run_id,
        category=category,
        strategy=strategy,
        status="done",
    )
    trace = AttackTrace(id=trace_id, attack_job_id=job_id)
    session.add_all([job, trace])
    session.flush()
    return job, trace


def seed_verdict(
    session: Session,
    trace_id: str = "trace-1",
    verdict_id: str = "v-1",
    layer: str = "external_final",
    outcome: str = "failed",
) -> Verdict:
    v = Verdict(
        id=verdict_id,
        attack_trace_id=trace_id,
        layer=layer,
        outcome=outcome,
        confidence=0.9,
        model="claude-sonnet-4-6",
    )
    session.add(v)
    session.flush()
    return v


def seed_vuln_report(
    session: Session,
    vr_id: str = "VR-001",
    severity: str = "high",
    status: str = "open",
    fix_status: str = "unfixed",
    content_markdown: str = "# VR-001\n\nbody here",
) -> VulnReport:
    vr = VulnReport(
        id="row-" + vr_id,
        vr_id=vr_id,
        vulnerability_class_id="VC-001",
        severity=severity,
        defcon=3,
        safety_score_0_100=42,
        status=status,
        fix_status=fix_status,
        target_fingerprint_at_discovery="fp-abc",
        content_markdown=content_markdown,
        content_html="",
    )
    session.add(vr)
    session.flush()
    return vr


def seed_cost(
    session: Session,
    role: str = "red_team",
    amount: str = "0.10",
    run_id: str = "run-1",
) -> CostLedgerEntry:
    row = CostLedgerEntry(
        id=f"cost-{role}-{amount}",
        run_id=run_id,
        agent_role=role,
        provider="openrouter",
        model="dolphin",
        input_tokens=100,
        output_tokens=50,
        cost_usd=Decimal(amount),
    )
    session.add(row)
    session.flush()
    return row


def seed_coverage(
    session: Session,
    category: str = "prompt_injection",
    strategy: str = "single_turn",
    attempts: int = 4,
    passes: int = 3,
    failures: int = 1,
) -> CoverageCellRow:
    row = CoverageCellRow(
        category=category,
        strategy=strategy,
        attempts=attempts,
        passes=passes,
        failures=failures,
        last_pass_rate=(passes / (passes + failures)) if (passes + failures) else 0.0,
    )
    session.add(row)
    session.flush()
    return row


def seed_delta_snapshot(
    session: Session,
    fingerprint: str = "fp-abc",
    aggregate: float = 0.75,
    by_cell: dict | None = None,
) -> DefenseDeltaSnapshot:
    import json

    row = DefenseDeltaSnapshot(
        fingerprint=fingerprint,
        aggregate_pass_rate=aggregate,
        by_cell_json=json.dumps(by_cell or {}),
    )
    session.add(row)
    session.flush()
    return row


def seed_regression_case(
    session: Session,
    case_id: str = "rc-1",
    vr_id: str = "VR-001",
) -> RegressionCase:
    row = RegressionCase(
        id=case_id,
        vr_id=vr_id,
        what_bug_this_catches="prevents prompt-injection regression on VR-001",
        case_json="{}",
    )
    session.add(row)
    session.flush()
    return row
