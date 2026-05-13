"""Unit tests for :class:`agentforge.regression.runner.RegressionRunner`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentforge.memory.models import RegressionCase as RegressionCaseRow
from agentforge.regression.floor import Floor, FloorEnforcer
from agentforge.regression.replay import Replay
from agentforge.regression.runner import RegressionRunner
from tests.unit.regression.conftest import FakeTargetExecutor


def _make_runner(
    *,
    regression_dir: Path,
    results_dir: Path,
    judge_outcomes: dict[str, str],
    session_factory=None,
    fake_judge,
) -> RegressionRunner:
    target = FakeTargetExecutor()
    judge = fake_judge(judge_outcomes)
    replay = Replay(target_executor=target, external_judge=judge)
    enforcer = FloorEnforcer(Floor(max_new_regressions_per_run=999))
    return RegressionRunner(
        replay=replay,
        floor_enforcer=enforcer,
        regression_dir=regression_dir,
        results_dir=results_dir,
        session_factory=session_factory,
    )


@pytest.mark.unit
def test_discover_cases_walks_dir(
    tmp_path: Path, make_regression_case, write_case_to_dir, fake_judge
) -> None:
    regression_dir = tmp_path / "regression"
    results_dir = tmp_path / "results"
    write_case_to_dir(regression_dir, make_regression_case(vr_id="VR-0001"))
    write_case_to_dir(regression_dir, make_regression_case(vr_id="VR-0002"))
    # Non-VR file must be ignored.
    (regression_dir / "README.md").write_text("ignored", encoding="utf-8")

    runner = _make_runner(
        regression_dir=regression_dir,
        results_dir=results_dir,
        judge_outcomes={"r1": "passed"},
        fake_judge=fake_judge,
    )
    cases = runner.discover_cases()
    assert sorted(c.vr_id for c in cases) == ["VR-0001", "VR-0002"]


@pytest.mark.unit
def test_run_all_writes_results_jsonl(
    tmp_path: Path, make_regression_case, write_case_to_dir, fake_judge
) -> None:
    regression_dir = tmp_path / "regression"
    results_dir = tmp_path / "results"
    write_case_to_dir(regression_dir, make_regression_case(vr_id="VR-0001"))

    runner = _make_runner(
        regression_dir=regression_dir,
        results_dir=results_dir,
        judge_outcomes={"r1": "failed"},
        fake_judge=fake_judge,
    )
    batch, floor_result = runner.run_all(target_fingerprint="fp-1")

    jsonl_files = list(results_dir.glob("regression_*.jsonl"))
    assert len(jsonl_files) == 1
    raw = jsonl_files[0].read_text(encoding="utf-8").splitlines()
    assert len(raw) == 2  # 1 header + 1 outcome
    header = json.loads(raw[0])
    assert "header" in header
    outcome = json.loads(raw[1])
    assert "outcome" in outcome
    assert outcome["outcome"]["vr_id"] == "VR-0001"

    assert batch.cases_run == 1
    assert batch.cases_failed_as_expected == ["VR-0001"]
    # No previous batch + max_new=999 → floor not exceeded.
    assert floor_result.floor_exceeded is False


@pytest.mark.unit
def test_run_one_finds_case_by_vr_id(
    tmp_path: Path, make_regression_case, write_case_to_dir, fake_judge
) -> None:
    regression_dir = tmp_path / "regression"
    results_dir = tmp_path / "results"
    write_case_to_dir(regression_dir, make_regression_case(vr_id="VR-0007"))

    runner = _make_runner(
        regression_dir=regression_dir,
        results_dir=results_dir,
        judge_outcomes={"r1": "failed"},
        fake_judge=fake_judge,
    )
    outcome = runner.run_one("VR-0007", target_fingerprint="fp-1")
    assert outcome.vr_id == "VR-0007"
    assert outcome.observed_outcome == "fail"


@pytest.mark.unit
def test_run_one_raises_on_missing_case(tmp_path: Path, fake_judge) -> None:
    runner = _make_runner(
        regression_dir=tmp_path / "regression",
        results_dir=tmp_path / "results",
        judge_outcomes={"r1": "passed"},
        fake_judge=fake_judge,
    )
    with pytest.raises(FileNotFoundError):
        runner.run_one("VR-9999", target_fingerprint="fp-1")


@pytest.mark.unit
def test_run_all_persists_last_run_outcome_via_repo(
    tmp_path: Path,
    make_regression_case,
    write_case_to_dir,
    in_memory_session_factory,
    fake_judge,
) -> None:
    """When a session_factory is provided, last_run_outcome is updated."""
    regression_dir = tmp_path / "regression"
    results_dir = tmp_path / "results"
    write_case_to_dir(regression_dir, make_regression_case(vr_id="VR-0001"))

    runner = _make_runner(
        regression_dir=regression_dir,
        results_dir=results_dir,
        judge_outcomes={"r1": "failed"},
        session_factory=in_memory_session_factory,
        fake_judge=fake_judge,
    )
    runner.run_all(target_fingerprint="fp-1")

    session = in_memory_session_factory()
    row = (
        session.query(RegressionCaseRow)
        .filter(RegressionCaseRow.vr_id == "VR-0001")
        .one_or_none()
    )
    assert row is not None
    assert row.last_run_outcome == "fail"
    assert row.last_run_at is not None
    session.close()


@pytest.mark.unit
def test_results_jsonl_first_line_is_header(
    tmp_path: Path, make_regression_case, write_case_to_dir, fake_judge
) -> None:
    regression_dir = tmp_path / "regression"
    results_dir = tmp_path / "results"
    write_case_to_dir(regression_dir, make_regression_case(vr_id="VR-0001"))
    write_case_to_dir(regression_dir, make_regression_case(vr_id="VR-0002"))

    runner = _make_runner(
        regression_dir=regression_dir,
        results_dir=results_dir,
        judge_outcomes={"r1": "passed"},
        fake_judge=fake_judge,
    )
    runner.run_all(target_fingerprint="fp-1")

    jsonl_path = next((results_dir).glob("regression_*.jsonl"))
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    assert "header" in first
    assert first["header"]["cases_run"] == 2
    for body in lines[1:]:
        assert "outcome" in json.loads(body)
