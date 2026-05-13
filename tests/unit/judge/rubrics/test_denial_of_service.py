"""Unit tests for denial-of-service rubric check functions.

Two tests per rubric: positive + negative. All four DoS rubrics are
deterministic short-circuits against `response`-side numeric fields.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from agentforge.judge.rubrics import denial_of_service as rubrics


@pytest.mark.unit
def test_latency_under_max_passes_when_under_budget() -> None:
    attack: dict = {}
    response = {"latency_seconds": 5.0}
    outcome = rubrics.check_latency_under_max(attack, response)
    assert outcome.passed is True


@pytest.mark.unit
def test_latency_under_max_fails_at_or_above_budget() -> None:
    attack: dict = {}
    response = {"latency_seconds": 45.0}
    outcome = rubrics.check_latency_under_max(attack, response)
    assert outcome.passed is False
    assert "45.0" in outcome.rationale


@pytest.mark.unit
def test_token_count_under_max_passes_when_under_budget() -> None:
    attack: dict = {}
    response = {"token_count": 1024}
    outcome = rubrics.check_token_count_under_max(attack, response)
    assert outcome.passed is True


@pytest.mark.unit
def test_token_count_under_max_fails_at_or_above_budget() -> None:
    attack: dict = {}
    response = {"token_count": 8192}
    outcome = rubrics.check_token_count_under_max(attack, response)
    assert outcome.passed is False
    assert "8192" in outcome.rationale


@pytest.mark.unit
def test_cost_per_request_under_max_passes_under_budget() -> None:
    attack: dict = {}
    response = {"cost_usd": Decimal("0.05")}
    outcome = rubrics.check_cost_per_request_under_max(attack, response)
    assert outcome.passed is True


@pytest.mark.unit
def test_cost_per_request_under_max_fails_at_or_above_budget() -> None:
    attack: dict = {}
    response = {"cost_usd": Decimal("0.50")}
    outcome = rubrics.check_cost_per_request_under_max(attack, response)
    assert outcome.passed is False


@pytest.mark.unit
def test_no_amplification_passes_at_or_under_cap() -> None:
    attack: dict = {}
    response = {"child_api_call_count": 2}
    outcome = rubrics.check_no_amplification(attack, response)
    assert outcome.passed is True


@pytest.mark.unit
def test_no_amplification_fails_above_cap() -> None:
    attack: dict = {}
    response = {"child_api_call_count": 17}
    outcome = rubrics.check_no_amplification(attack, response)
    assert outcome.passed is False
    assert "17" in outcome.rationale
