"""Regression tests for the fixture-load path in scripts/seed_demo_data.py.

The seeder loads a captured snapshot of the live DB (`scripts/fixtures/seed_dump.sql`)
so a fresh Railway deploy starts with the same data shape the operator's
local dashboard had at submission time. Falls back to the synthetic
_seed_* functions if the fixture is missing.

These tests pin:
  - The fixture file exists and parses as expected (>= one INSERT per
    canonical table).
  - The fixture-load path produces the expected row counts when applied
    to a fresh empty schema.
  - The fallback (synthetic seed) path fires when the fixture is hidden.
  - The idempotency check still works (re-running on a populated DB
    is a no-op).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

# Make scripts/ importable as a module.
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import seed_demo_data as seeder  # noqa: E402

from agentforge.memory.db import init_db, make_session_factory  # noqa: E402
from agentforge.memory.models import (  # noqa: E402
    AttackJob,
    AttackTrace,
    CostLedgerEntry,
    CoverageCellRow,
    DefenseDeltaSnapshot,
    RegressionCase,
    Run,
    Verdict,
    VulnerabilityClass,
    VulnReport,
)

# Expected row counts after fixture load. Pinned to the operator's submission-
# time DB shape; bumping these requires regenerating scripts/fixtures/seed_dump.sql
# from a fresh live DB and updating these counts in lockstep.
_EXPECTED_COUNTS: dict[type, int] = {
    Run: 13,
    AttackJob: 73,
    AttackTrace: 42,
    Verdict: 84,
    VulnReport: 7,
    VulnerabilityClass: 6,
    CostLedgerEntry: 178,
    CoverageCellRow: 55,
    DefenseDeltaSnapshot: 2,
    RegressionCase: 5,
}
_EXPECTED_TOTAL_INSERTS = sum(_EXPECTED_COUNTS.values())


def _make_empty_db(tmp_path: Path) -> tuple[Engine, object]:
    """Spin up a fresh SQLite + create the schema via SQLAlchemy create_all.

    Production path uses `alembic upgrade head` instead -- but the resulting
    schema is structurally equivalent for the columns the fixture inserts
    into, because the fixture uses explicit column names rather than
    positional VALUES (the regression that motivated this whole design).
    """
    db_path = tmp_path / "seed_test.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    init_db(engine)
    factory = make_session_factory(engine)
    return engine, factory


@pytest.fixture
def patched_seeder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Patch seeder.get_session_factory to return a tmp-DB session factory."""
    engine, factory = _make_empty_db(tmp_path)
    monkeypatch.setattr(seeder, "get_session_factory", lambda: factory)
    return factory


@pytest.mark.unit
def test_fixture_file_exists_and_parses_as_inserts() -> None:
    """The committed fixture file must be present and contain real INSERTs
    for every canonical table — otherwise a Railway deploy lands an empty
    dashboard."""
    fixture = seeder._FIXTURE_PATH
    assert fixture.exists(), f"fixture missing at {fixture}"
    text = fixture.read_text(encoding="utf-8")
    canonical_tables = (
        "runs",
        "attack_jobs",
        "attack_traces",
        "verdicts",
        "vuln_reports",
        "vulnerability_classes",
        "cost_ledger",
        "coverage_cells",
        "defense_delta_snapshots",
        "regression_cases",
    )
    for table in canonical_tables:
        assert f'INSERT INTO "{table}"' in text, f"fixture has no INSERTs for {table!r}"


@pytest.mark.unit
def test_fixture_loads_into_empty_db_with_expected_row_counts(patched_seeder) -> None:
    """Run seed() against an empty DB; verify the fixture path fired and
    produced exactly the pinned row counts."""
    factory = patched_seeder
    rc = seeder.seed(force=False)
    assert rc == 0, "seed() should return 0 on success"
    session = factory()
    try:
        for model, expected in _EXPECTED_COUNTS.items():
            got = session.query(model).count()
            assert got == expected, f"{model.__name__}: expected {expected} rows, got {got}"
    finally:
        session.close()


@pytest.mark.unit
def test_synthetic_seed_runs_when_fixture_missing(
    patched_seeder, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the fixture path doesn't exist, the seeder falls through to the
    original synthetic _seed_* functions. Pins the safety-net path."""
    factory = patched_seeder
    # Point the seeder at a non-existent fixture path.
    monkeypatch.setattr(seeder, "_FIXTURE_PATH", tmp_path / "does-not-exist.sql")
    rc = seeder.seed(force=False)
    assert rc == 0
    session = factory()
    try:
        # Synthetic seed produces ~3 runs (not the 13 the fixture has).
        # Just confirm SOME rows landed and we didn't get a fixture-count match.
        n_runs = session.query(Run).count()
        assert n_runs > 0, "synthetic seed must produce at least one run"
        assert n_runs != _EXPECTED_COUNTS[Run], (
            "synthetic seed accidentally matched fixture count -- "
            "make sure the fallback path is actually firing, not the fixture"
        )
    finally:
        session.close()


@pytest.mark.unit
def test_idempotency_skip_when_db_already_populated(patched_seeder) -> None:
    """Run seed twice — the second invocation must short-circuit without
    touching the DB. Pins the existing idempotency contract."""
    factory = patched_seeder
    # First run: load fixture.
    assert seeder.seed(force=False) == 0
    session = factory()
    try:
        first_count = session.query(Run).count()
    finally:
        session.close()

    # Second run: should detect existing data and skip.
    assert seeder.seed(force=False) == 0
    session = factory()
    try:
        second_count = session.query(Run).count()
    finally:
        session.close()

    assert first_count == second_count, (
        f"idempotency broken: second seed() invocation changed Run count "
        f"from {first_count} to {second_count}"
    )


@pytest.mark.unit
def test_force_flag_replays_seed_on_populated_db(patched_seeder) -> None:
    """`seed(force=True)` bypasses the idempotency check and re-loads.

    The fixture INSERTs use explicit primary keys, so re-loading on a
    populated DB will fail with a primary-key conflict. We verify the
    failure surfaces (return code != 0) rather than silently corrupting
    data — that's the contract _force is meant to expose.
    """
    _ = patched_seeder  # fixture activates the patch; the factory itself isn't needed here
    # First run: clean load.
    assert seeder.seed(force=False) == 0
    # Second with force: should attempt re-insert, fail on PK conflict, return nonzero.
    rc = seeder.seed(force=True)
    assert rc != 0, "force re-load should surface PK conflicts as non-zero rc"
