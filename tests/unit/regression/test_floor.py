"""Unit tests for :class:`agentforge.regression.floor.FloorEnforcer`."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentforge.regression.case_schema import ReplayBatch
from agentforge.regression.floor import Floor, FloorEnforcer


def _batch(
    *,
    failed: list[str] | None = None,
    passed: list[str] | None = None,
    errored: list[str] | None = None,
) -> ReplayBatch:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    failed = failed or []
    passed = passed or []
    errored = errored or []
    return ReplayBatch(
        started_at=now,
        ended_at=now,
        target_fingerprint="f" * 64,
        cases_run=len(failed) + len(passed) + len(errored),
        cases_passed_unexpectedly=passed,
        cases_failed_as_expected=failed,
        cases_errored=errored,
        new_regressions=[],
    )


@pytest.mark.unit
def test_floor_empty_batch_passes() -> None:
    enforcer = FloorEnforcer(Floor())
    result = enforcer.evaluate(_batch())
    assert result.floor_exceeded is False
    assert result.exit_code == 0
    assert result.new_regressions == []


@pytest.mark.unit
def test_new_regression_with_no_previous_batch_counts_as_new() -> None:
    """With no baseline, every failing vr_id is a new regression."""
    enforcer = FloorEnforcer(Floor(max_new_regressions_per_run=0))
    result = enforcer.evaluate(_batch(failed=["VR-0001"]))
    assert result.new_regressions == ["VR-0001"]
    assert result.floor_exceeded is True
    assert result.exit_code == 1


@pytest.mark.unit
def test_known_failing_case_never_counts_as_new() -> None:
    """Whitelist entries never trigger the floor even when failing."""
    enforcer = FloorEnforcer(
        Floor(
            max_new_regressions_per_run=0,
            known_failing_cases=["VR-0001", "VR-0002"],
        )
    )
    result = enforcer.evaluate(_batch(failed=["VR-0001", "VR-0002", "VR-0003"]))
    assert "VR-0001" not in result.new_regressions
    assert "VR-0002" not in result.new_regressions
    assert "VR-0003" in result.new_regressions


@pytest.mark.unit
def test_unexpected_pass_listed_as_fix_candidate() -> None:
    """Cases that were failing previously but now pass must surface in
    ``unexpected_passes`` as fix candidates."""
    enforcer = FloorEnforcer(Floor())
    previous = _batch(failed=["VR-0001"], passed=[])
    current = _batch(failed=[], passed=["VR-0001"])
    result = enforcer.evaluate(current, previous_batch=previous)
    assert result.unexpected_passes == ["VR-0001"]
    assert result.new_regressions == []
    assert result.floor_exceeded is False


@pytest.mark.unit
def test_floor_exceeded_when_new_regressions_exceed_max() -> None:
    enforcer = FloorEnforcer(Floor(max_new_regressions_per_run=1))
    # No previous batch → all failing cases count as new (3 > 1).
    result = enforcer.evaluate(_batch(failed=["VR-0001", "VR-0002", "VR-0003"]))
    assert result.floor_exceeded is True
    assert len(result.new_regressions) == 3
    assert result.exit_code == 1


@pytest.mark.unit
def test_exit_code_1_on_floor_violation() -> None:
    enforcer = FloorEnforcer(Floor(max_new_regressions_per_run=0))
    result = enforcer.evaluate(_batch(failed=["VR-0099"]))
    assert result.exit_code == 1


@pytest.mark.unit
def test_floor_from_json(tmp_path: Path) -> None:
    """:meth:`FloorEnforcer.from_json` round-trips ``evals/floor.json`` schema."""
    p = tmp_path / "floor.json"
    p.write_text(
        json.dumps(
            {
                "max_new_regressions_per_run": 2,
                "known_failing_cases": ["VR-0050"],
                "judge_floor": {
                    "external_final": {"precision": 0.85, "recall": 0.80, "f1": 0.82}
                },
            }
        ),
        encoding="utf-8",
    )
    enforcer = FloorEnforcer.from_json(p)
    assert enforcer.floor.max_new_regressions_per_run == 2
    assert enforcer.floor.known_failing_cases == ["VR-0050"]
    assert enforcer.floor.judge_floor["external_final"]["precision"] == 0.85


@pytest.mark.unit
def test_previously_failing_stays_failing_is_not_a_new_regression() -> None:
    """Cases failing in BOTH the previous and current batch are still-broken,
    not newly broken — they do NOT count toward the new-regression floor."""
    enforcer = FloorEnforcer(Floor(max_new_regressions_per_run=0))
    previous = _batch(failed=["VR-0001"])
    current = _batch(failed=["VR-0001"])
    result = enforcer.evaluate(current, previous_batch=previous)
    assert result.new_regressions == []
    assert result.floor_exceeded is False
