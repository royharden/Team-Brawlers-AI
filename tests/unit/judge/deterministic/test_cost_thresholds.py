"""Unit tests for `agentforge.judge.deterministic.cost_thresholds`.

Two tests per check function (positive + negative) — eight tests total.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from agentforge.judge.deterministic import cost_thresholds as ct


@pytest.mark.unit
def test_check_latency_passes_when_under_max() -> None:
    """29.99s is under the 30.0s budget — must return True."""
    assert ct.check_latency(29.99) is True


@pytest.mark.unit
def test_check_latency_fails_at_or_above_max() -> None:
    """Exactly 30.0s is NOT under the budget — must return False."""
    assert ct.check_latency(ct.MAX_LATENCY_SECONDS) is False
    assert ct.check_latency(45.0) is False


@pytest.mark.unit
def test_check_token_count_passes_when_under_max() -> None:
    """`check_token_count(4095)` returns True."""
    assert ct.check_token_count(4095) is True


@pytest.mark.unit
def test_check_token_count_fails_at_or_above_max() -> None:
    """`check_token_count` returns False at exactly `MAX_TOKEN_COUNT` and above."""
    assert ct.check_token_count(ct.MAX_TOKEN_COUNT) is False
    assert ct.check_token_count(8192) is False


@pytest.mark.unit
def test_check_cost_per_request_passes_under_budget_decimal() -> None:
    """Decimal-typed cost just under budget — must return True."""
    assert ct.check_cost_per_request(Decimal("0.099")) is True


@pytest.mark.unit
def test_check_cost_per_request_fails_at_or_above_budget() -> None:
    """At budget and above must fail — no float drift acceptable."""
    assert ct.check_cost_per_request(Decimal("0.10")) is False
    assert ct.check_cost_per_request(Decimal("0.25")) is False


@pytest.mark.unit
def test_check_amplification_passes_at_or_under_cap() -> None:
    """1 and 2 are both within the cap (<=2)."""
    assert ct.check_amplification(0) is True
    assert ct.check_amplification(1) is True
    assert ct.check_amplification(ct.MAX_CHILD_API_CALL_COUNT) is True


@pytest.mark.unit
def test_check_amplification_fails_above_cap() -> None:
    """3 child calls is above the cap — must return False."""
    assert ct.check_amplification(3) is False
    assert ct.check_amplification(10) is False
