"""Unit tests for ``scripts/generate_sample_vrs.py`` — sub-plan Next03 §4.1.

The generator is a developer tool that exercises the full DocumentationAgent
path against synthetic responses. After Next03 §4.1 it also persists into
``vuln_reports`` / ``vulnerability_classes`` / ``regression_cases`` (the
seeder still owns the demo's reading dataset; this script is for live-path
exercise + supplementing the dataset).

These tests pin:
  - DB rows are written when the script's main() completes.
  - Re-running the script does not crash on collisions (Idempotency).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make scripts/ importable as a module.
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import generate_sample_vrs as gsv  # noqa: E402

from agentforge.memory.db import init_db, make_engine, make_session_factory  # noqa: E402
from agentforge.memory.models import (  # noqa: E402
    RegressionCase,
    VulnerabilityClass,
    VulnReport,
)


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the script's `get_engine()` at a tmp SQLite file so the test
    doesn't touch the operator's real DB. The script also uses
    `make_session_factory(get_engine())` so a single tmp engine wins."""
    db_path = tmp_path / "sample_vrs.sqlite"
    db_url = f"sqlite:///{db_path}"

    engine = make_engine(db_url)
    init_db(engine)
    factory = make_session_factory(engine)

    # Patch the script's get_engine + make_session_factory imports to return
    # ours — the script calls them at the top of main().
    monkeypatch.setattr(gsv, "get_engine", lambda: engine)
    monkeypatch.setattr(gsv, "init_db", lambda engine=engine: None)
    monkeypatch.setattr(gsv, "make_session_factory", lambda _: factory)
    yield factory


def _argv(tmp_path: Path) -> list[str]:
    """Build the CLI argv for an isolated run rooted at tmp_path."""
    return [
        "--reports-dir",
        str(tmp_path / "reports"),
        "--regression-dir",
        str(tmp_path / "regression"),
        "--notifier-queue",
        str(tmp_path / "notifier_queue.jsonl"),
    ]


@pytest.mark.unit
def test_generate_sample_vrs_inserts_db_rows(
    tmp_path: Path,
    isolated_db,
) -> None:
    """`main()` writes a vuln_reports row + a regression_cases row + (if new)
    a vulnerability_classes row per emitted seed (sub-plan Next03 §4.1)."""
    rc = gsv.main(_argv(tmp_path))
    assert rc == 0, "script should exit 0 on the synthetic seed batch"

    factory = isolated_db
    session = factory()
    try:
        n_vrs = session.query(VulnReport).count()
        n_cases = session.query(RegressionCase).count()
        n_vc = session.query(VulnerabilityClass).count()
    finally:
        session.close()

    # Each emitted seed produces one VR row + one regression_cases row + one
    # vulnerability_classes row (deduped per dedupe-key). Seeds whose
    # synthetic response doesn't fail any rubric are skipped silently — pin
    # the contract that we always emit at least 3 (the canonical demo set).
    assert n_vrs >= 3
    assert n_cases == n_vrs
    assert n_vc >= 1


@pytest.mark.unit
def test_generate_sample_vrs_rerun_doesnt_crash_on_db_collisions(
    tmp_path: Path,
    isolated_db,
) -> None:
    """Re-running the generator does not crash — DB collisions on
    regression_case.vr_id are caught + skipped (sub-plan Next03 §4.1).

    The script's monotonic .vr_counter ensures normal reruns generate FRESH
    vr_ids and so don't collide; this test simulates a partial-failure rerun
    by resetting the counter so the second invocation tries to write the
    same vr_ids again.
    """
    factory = isolated_db
    counter_path = Path(tmp_path) / "reports" / ".vr_counter"

    # First run — writes 4 VRs with vr_ids derived from whatever the counter
    # already had (counter lives under reports_dir, so it's tmp-isolated).
    rc1 = gsv.main(_argv(tmp_path))
    assert rc1 == 0

    session = factory()
    try:
        n_after_first = session.query(VulnReport).count()
    finally:
        session.close()
    assert n_after_first >= 3

    # Reset the counter so the second run will try the same vr_ids.
    if counter_path.exists():
        counter_path.write_text("0\n", encoding="utf-8")

    # Second run should not crash; per-seed collisions are caught.
    rc2 = gsv.main(_argv(tmp_path))
    assert rc2 == 0

    session = factory()
    try:
        n_after_second = session.query(VulnReport).count()
    finally:
        session.close()

    # Collisions on the regression_case.vr_id UNIQUE constraint short-circuit
    # the per-seed loop after the vuln_report insert; re-run row count grows
    # only if no collision was triggered (depends on which insert failed first).
    assert n_after_second >= n_after_first
