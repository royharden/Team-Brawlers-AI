"""Unit tests for ``scripts/backfill_attack_id.py`` — Next06 §4.

Closes AgDR-0026 follow-on #1: rows persisted before migration 0002
added the `attack_id` column carry the same id in
`target_request_json["trace_id"]`; the script derives the missing
column from the JSON.

These tests pin:
  - Pre-migration rows (NULL attack_id) gain the derived id.
  - Post-migration rows (already populated) are untouched.
  - Rows whose `target_request_json` lacks `trace_id` are skipped.
  - Re-run is idempotent.
  - `--dry-run` reports counts but writes nothing.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

# Make scripts/ importable as a module.
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import backfill_attack_id as bf  # noqa: E402

from agentforge.memory.db import init_db, make_engine, make_session_factory  # noqa: E402
from agentforge.memory.models import (  # noqa: E402
    AttackJob,
    AttackTrace,
    Run,
)


def _seed_trace(
    session,
    *,
    row_id: str,
    job_id: str,
    run_id: str,
    request_json: dict | str | None,
    attack_id: str | None,
) -> None:
    """Insert a Run/AttackJob/AttackTrace triple with the given lineage state.

    Uses session.merge so the helper is safe to call multiple times in a
    single test with the same run_id. Each merge is flushed immediately
    so FK constraints on the next insert can resolve.
    """
    session.merge(
        Run(
            id=run_id,
            started_at=datetime.now(UTC).replace(tzinfo=None),
            run_type="exploratory",
            status="completed",
        )
    )
    session.flush()
    session.merge(
        AttackJob(
            id=job_id,
            run_id=run_id,
            category="prompt_injection",
            strategy="single_turn",
            status="completed",
        )
    )
    session.flush()
    if isinstance(request_json, dict):
        raw = json.dumps(request_json)
    elif isinstance(request_json, str):
        raw = request_json
    else:
        raw = "{}"
    session.add(
        AttackTrace(
            id=row_id,
            attack_job_id=job_id,
            attack_id=attack_id,
            target_request_json=raw,
        )
    )
    session.flush()


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "backfill.sqlite"
    engine = make_engine(f"sqlite:///{db_path}")
    init_db(engine)
    return make_session_factory(engine)


@pytest.mark.unit
def test_backfill_populates_attack_id_from_trace_id_json(session_factory) -> None:
    """Pre-migration row (attack_id IS NULL but JSON carries trace_id)
    → backfill writes the derived value into attack_id."""
    session = session_factory()
    try:
        _seed_trace(
            session,
            row_id="row-pre",
            job_id="job-pre",
            run_id="run-pre",
            request_json={"endpoint": "/x", "trace_id": "atk-uuid-aaaa"},
            attack_id=None,
        )
        session.commit()
    finally:
        session.close()

    stats = bf.backfill_attack_ids(session_factory)
    assert stats["scanned"] == 1
    assert stats["updated"] == 1
    assert stats["no_trace_id_in_json"] == 0

    session = session_factory()
    try:
        row = session.query(AttackTrace).filter_by(id="row-pre").one()
        assert row.attack_id == "atk-uuid-aaaa"
    finally:
        session.close()


@pytest.mark.unit
def test_backfill_leaves_already_populated_rows_untouched(session_factory) -> None:
    """Post-migration row (attack_id already set) is skipped by the WHERE."""
    session = session_factory()
    try:
        _seed_trace(
            session,
            row_id="row-post",
            job_id="job-post",
            run_id="run-post",
            request_json={"trace_id": "atk-different-id"},
            attack_id="atk-already-here",
        )
        session.commit()
    finally:
        session.close()

    stats = bf.backfill_attack_ids(session_factory)
    assert stats["scanned"] == 0  # filtered out by WHERE attack_id IS NULL

    session = session_factory()
    try:
        row = session.query(AttackTrace).filter_by(id="row-post").one()
        assert row.attack_id == "atk-already-here"
    finally:
        session.close()


@pytest.mark.unit
def test_backfill_skips_rows_without_trace_id_in_json(session_factory) -> None:
    """A pre-migration row whose JSON has no trace_id is reported but
    not updated — keeps attack_id=NULL so the operator can investigate."""
    session = session_factory()
    try:
        _seed_trace(
            session,
            row_id="row-orphan",
            job_id="job-orphan",
            run_id="run-orphan",
            request_json={"endpoint": "/x"},  # no trace_id key
            attack_id=None,
        )
        _seed_trace(
            session,
            row_id="row-malformed",
            job_id="job-malformed",
            run_id="run-malformed",
            request_json="this is not json {{{",
            attack_id=None,
        )
        session.commit()
    finally:
        session.close()

    stats = bf.backfill_attack_ids(session_factory)
    assert stats["scanned"] == 2
    assert stats["updated"] == 0
    assert stats["no_trace_id_in_json"] == 2

    session = session_factory()
    try:
        for rid in ("row-orphan", "row-malformed"):
            row = session.query(AttackTrace).filter_by(id=rid).one()
            assert row.attack_id is None
    finally:
        session.close()


@pytest.mark.unit
def test_backfill_is_idempotent(session_factory) -> None:
    """Re-running the script on an already-backfilled DB finds nothing
    to update — operator can rerun safely after partial failures."""
    session = session_factory()
    try:
        _seed_trace(
            session,
            row_id="row-idemp",
            job_id="job-idemp",
            run_id="run-idemp",
            request_json={"trace_id": "atk-idemp-id"},
            attack_id=None,
        )
        session.commit()
    finally:
        session.close()

    first = bf.backfill_attack_ids(session_factory)
    second = bf.backfill_attack_ids(session_factory)

    assert first["updated"] == 1
    assert second["scanned"] == 0
    assert second["updated"] == 0


@pytest.mark.unit
def test_backfill_dry_run_reports_but_does_not_write(session_factory) -> None:
    """--dry-run returns the same stats but the row stays NULL."""
    session = session_factory()
    try:
        _seed_trace(
            session,
            row_id="row-dry",
            job_id="job-dry",
            run_id="run-dry",
            request_json={"trace_id": "atk-dry-id"},
            attack_id=None,
        )
        session.commit()
    finally:
        session.close()

    stats = bf.backfill_attack_ids(session_factory, dry_run=True)
    assert stats["updated"] == 1

    session = session_factory()
    try:
        row = session.query(AttackTrace).filter_by(id="row-dry").one()
        assert row.attack_id is None
    finally:
        session.close()
