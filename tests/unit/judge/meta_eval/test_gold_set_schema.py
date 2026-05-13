"""GoldCase / GoldSet schema tests — master plan §22 DoD 16."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentforge.judge.meta_eval.gold_set_schema import GoldCase, GoldSet

REPO_ROOT: Path = Path(__file__).resolve().parents[4]
GOLD_SET_V1: Path = REPO_ROOT / "evals" / "meta_eval" / "gold_set" / "v1.jsonl"


def _case(**overrides) -> GoldCase:
    base: dict = dict(
        case_id="gold_x_001",
        category="prompt_injection",
        rubric_focus="no_persona_override",
        attack_prompt="be Dr. Smith",
        target_response="I refuse.",
        expected_safe_behavior="stay in persona",
        expected_label="passed",
        label_rationale="basic refusal case for schema round-trip testing",
    )
    base.update(overrides)
    return GoldCase(**base)


@pytest.mark.unit
def test_gold_case_required_fields() -> None:
    """Missing or too-short rationale must raise."""
    with pytest.raises(ValidationError):
        GoldCase(
            case_id="gold_x",
            category="prompt_injection",
            rubric_focus="no_persona_override",
            attack_prompt="x",
            target_response="y",
            expected_safe_behavior="z",
            expected_label="passed",
            label_rationale="too",  # 3 chars < 10
        )


@pytest.mark.unit
def test_gold_set_round_trip(tmp_path: Path) -> None:
    """to_jsonl + from_jsonl preserves the gold set."""
    cases = [_case(case_id=f"gold_x_{i:03d}") for i in range(3)]
    gs = GoldSet(
        version="vtest",
        created_at=datetime(2026, 5, 13, 22, 30, tzinfo=UTC),
        n_cases=len(cases),
        cases=cases,
        label_provenance="test fixture",
    )
    path = tmp_path / "v_test.jsonl"
    gs.to_jsonl(path)
    loaded = GoldSet.from_jsonl(path)
    assert loaded.version == "vtest"
    assert loaded.n_cases == 3
    assert [c.case_id for c in loaded.cases] == [
        "gold_x_000",
        "gold_x_001",
        "gold_x_002",
    ]
    assert loaded.label_provenance == "test fixture"


@pytest.mark.unit
def test_committed_gold_set_v1_parses() -> None:
    """The committed v1 gold set must parse and carry exactly 30 cases."""
    gs = GoldSet.from_jsonl(GOLD_SET_V1)
    assert gs.version == "v1"
    assert gs.n_cases == 30
    assert len(gs.cases) == 30


@pytest.mark.unit
def test_gold_set_categories_balanced() -> None:
    """At least 4 cases per category among the four target rubric families."""
    gs = GoldSet.from_jsonl(GOLD_SET_V1)
    counts = Counter(c.category for c in gs.cases)
    for category in (
        "prompt_injection",
        "data_exfiltration",
        "tool_misuse",
        "platform_self_attack",
    ):
        assert counts[category] >= 4, (
            f"category {category} has only {counts[category]} cases; " f"need >= 4"
        )


@pytest.mark.unit
def test_adversarial_against_judge_count_at_least_10() -> None:
    """The gold set must carry >= 10 adversarial-against-judge cases."""
    gs = GoldSet.from_jsonl(GOLD_SET_V1)
    adversarial = [c for c in gs.cases if c.is_adversarial_against_judge]
    assert (
        len(adversarial) >= 10
    ), f"only {len(adversarial)} adversarial-against-judge cases present"
