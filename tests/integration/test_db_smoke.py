"""DB smoke tests — master plan §5.

Confirms:
1. `init_db()` creates every expected table when pointed at an in-memory
   SQLite engine.
2. The CHECK constraint on `regression_cases.what_bug_this_catches` rejects
   empty-string inserts (testing-discipline contract).
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from agentforge.memory.db import init_db, make_engine, make_session_factory
from agentforge.memory.models import (
    RegressionCase,
    Run,
    VulnerabilityClass,
    VulnReport,
)

EXPECTED_TABLES = {
    "runs",
    "attack_jobs",
    "attack_traces",
    "verdicts",
    "vulnerability_classes",
    "vuln_reports",
    "regression_cases",
    "cost_ledger",
    "coverage_cells",
    "defense_delta_snapshots",
    "agent_messages",
    "flight_events",
}


@pytest.fixture
def memory_engine() -> Engine:
    """Fresh in-memory SQLite engine with FK enforcement enabled.

    `init_db()` is called once so tables exist before any test query.
    """
    engine = make_engine("sqlite:///:memory:")

    # Belt-and-suspenders: ensure foreign keys are ON even though make_engine
    # registers a listener (the listener fires on real connects; for the
    # in-memory case we re-enable explicitly on each connection).
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn: object, _record: object) -> None:
        cur = dbapi_conn.cursor()  # type: ignore[attr-defined]
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    init_db(engine)
    return engine


@pytest.mark.integration
def test_init_db_creates_all_tables(memory_engine: Engine) -> None:
    """`init_db()` creates every Phase-1 table (12 tables — master plan §5.2)."""
    with memory_engine.connect() as conn:
        rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).all()
    found = {r[0] for r in rows}
    missing = EXPECTED_TABLES - found
    assert not missing, f"missing tables: {missing}; got {sorted(found)}"


@pytest.mark.integration
def test_regression_case_requires_what_bug_this_catches(memory_engine: Engine) -> None:
    """Empty `what_bug_this_catches` must violate the CHECK constraint."""
    factory = make_session_factory(memory_engine)
    session = factory()
    try:
        # Set up the FK chain: VulnerabilityClass -> VulnReport -> RegressionCase.
        # Commit VC first so its PK is durable before VR references it.
        vc = VulnerabilityClass(
            id="VC-0001",
            dedupe_key_sha256="a" * 64,
            category="prompt_injection",
            target_endpoint="brief",
            normalized_objective="exfiltrate ssn",
        )
        session.add(vc)
        session.commit()
        vr = VulnReport(
            id="00000000-0000-0000-0000-000000000001",
            vr_id="VR-0001",
            vulnerability_class_id="VC-0001",
            severity="high",
            target_fingerprint_at_discovery="f" * 64,
        )
        session.add(vr)
        session.commit()

        bad = RegressionCase(
            id="00000000-0000-0000-0000-000000000002",
            vr_id="VR-0001",
            what_bug_this_catches="",  # CHECK length > 0
        )
        session.add(bad)
        with pytest.raises(Exception):  # noqa: B017 — IntegrityError from sqlite
            session.commit()
        session.rollback()

        # Sanity: a non-empty value succeeds.
        good = RegressionCase(
            id="00000000-0000-0000-0000-000000000003",
            vr_id="VR-0001",
            what_bug_this_catches="catches SSN-in-output regression after VR-0001 fix",
        )
        session.add(good)
        session.commit()
        assert (
            session.query(RegressionCase)
            .filter_by(id="00000000-0000-0000-0000-000000000003")
            .one()
            .what_bug_this_catches.startswith("catches SSN")
        )
    finally:
        session.close()


@pytest.mark.integration
def test_run_insert_roundtrip(memory_engine: Engine) -> None:
    """Smoke: a Run row can be inserted + queried (sanity)."""
    factory = make_session_factory(memory_engine)
    session = factory()
    try:
        run = Run(id="run-1", run_type="smoke", status="completed")
        session.add(run)
        session.commit()
        out = session.query(Run).filter_by(id="run-1").one()
        assert out.run_type == "smoke"
        assert out.status == "completed"
    finally:
        session.close()
