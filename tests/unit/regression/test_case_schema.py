"""Unit tests for :mod:`agentforge.regression.case_schema`."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentforge.regression.case_schema import (
    RegressionCase,
    RegressionMetadata,
    ReplayBatch,
    ReplayOutcome,
)


@pytest.mark.unit
def test_regression_case_round_trip(tmp_path: Path, make_regression_case) -> None:
    """Write + read JSON must reconstruct a structurally identical case."""
    case = make_regression_case()
    path = tmp_path / "VR-0001.json"
    case.to_json(path)
    loaded = RegressionCase.from_json(path)
    assert loaded.model_dump(mode="json") == case.model_dump(mode="json")


@pytest.mark.unit
def test_what_bug_this_catches_required(make_regression_case) -> None:
    """Empty string for `what_bug_this_catches` must raise."""
    with pytest.raises(ValidationError):
        make_regression_case(what_bug_this_catches="")
    with pytest.raises(ValidationError):
        make_regression_case(what_bug_this_catches="   ")


@pytest.mark.unit
def test_replay_outcome_pydantic_round_trip() -> None:
    """:class:`ReplayOutcome` must survive ``model_dump_json`` → ``model_validate_json``."""
    oc = ReplayOutcome(
        vr_id="VR-0042",
        case_id="prompt_injection_persona_override",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        target_fingerprint="abc" * 21 + "x",  # 64 chars
        observed_outcome="fail",
        expected_outcome="fail",
        matched_expected=True,
        judge_verdict_summary="External Final Judge: failed (0/3 rubrics passed)",
        judge_outcomes={"r1": "failed", "r2": "passed"},
        latency_ms=42.5,
        error=None,
    )
    raw = oc.model_dump_json()
    loaded = ReplayOutcome.model_validate_json(raw)
    assert loaded.observed_outcome == "fail"
    assert loaded.matched_expected is True
    assert loaded.judge_outcomes == {"r1": "failed", "r2": "passed"}


@pytest.mark.unit
def test_replay_batch_aggregates_lists_correctly() -> None:
    """:class:`ReplayBatch` keeps every category list separately."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    batch = ReplayBatch(
        started_at=now,
        ended_at=now,
        target_fingerprint="f" * 64,
        cases_run=4,
        cases_passed_unexpectedly=["VR-0002"],
        cases_failed_as_expected=["VR-0001", "VR-0003"],
        cases_errored=["VR-0004"],
        new_regressions=["VR-0003"],
    )
    assert batch.cases_run == 4
    assert batch.cases_passed_unexpectedly == ["VR-0002"]
    assert batch.cases_failed_as_expected == ["VR-0001", "VR-0003"]
    assert batch.cases_errored == ["VR-0004"]
    assert batch.new_regressions == ["VR-0003"]


@pytest.mark.unit
def test_curator_emitted_json_loads_via_from_json(
    tmp_path: Path, write_raw_case_json, raw_case_dict
) -> None:
    """A JSON dict shaped exactly like ``RegressionCurator.emit_case`` writes
    must load cleanly via :meth:`RegressionCase.from_json` — guards against
    schema drift between curator and runner."""
    path = write_raw_case_json(tmp_path, raw_case_dict())
    case = RegressionCase.from_json(path)
    assert case.vr_id == "VR-0001"
    assert case.regression_metadata.replay_command == "tb regress --case VR-0001"
    assert case.regression_metadata.expected_outcome == "fail"


@pytest.mark.unit
def test_metadata_extra_fields_allowed() -> None:
    """RegressionMetadata allows extra fields so curator extensions don't break
    the runner."""
    meta = RegressionMetadata.model_validate(
        {
            "originating_run_id": "run-x",
            "target_fingerprint_at_discovery": "f" * 64,
            "replay_command": "tb regress --case VR-0001",
            "expected_outcome": "fail",
            "emitted_at": "2026-01-01T00:00:00+00:00",
            "extra_field": "tolerated",
        }
    )
    # Survival of the extra field is best-effort (Pydantic stores it under
    # __pydantic_extra__); the important thing is that validation doesn't
    # raise on a curator update.
    assert meta.originating_run_id == "run-x"
