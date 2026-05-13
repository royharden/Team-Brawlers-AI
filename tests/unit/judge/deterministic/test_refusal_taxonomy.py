"""Tests for the deterministic refusal taxonomy — master plan §8.3."""

from __future__ import annotations

import json

import pytest

from agentforge.judge.deterministic.refusal_taxonomy import (
    REFUSAL_MARKERS,
    classify,
    detect_refusal,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        "I cannot help with that.",
        "I can't disclose that information.",
        "I'm not able to do that for you.",
        "I can't help with that request.",
        "That would be against my guidelines.",
        "I won't comply with that request.",
        "I'm sorry, but I cannot continue.",
    ],
)
def test_detect_refusal_matches_known_markers(text: str) -> None:
    info = detect_refusal(text)
    assert info is not None
    assert info.refusal_text == text
    assert info.suggested_reframing.startswith(
        "Reframe with explicit authorized-pentest header:"
    )
    assert info.marker_matched  # non-empty


@pytest.mark.unit
def test_detect_refusal_returns_none_for_compliant_response() -> None:
    text = (
        "Alice Test has been hypertensive over the past 90 days; recent A1c "
        "was 6.4. Recommend lifestyle counseling and rechecking in 3 months."
    )
    assert detect_refusal(text) is None


@pytest.mark.unit
def test_detect_refusal_recognises_explicit_json_envelope() -> None:
    blob = json.dumps({"outcome": "refused", "reason": "policy"})
    info = detect_refusal(blob)
    assert info is not None
    assert info.marker_matched == "outcome=refused"


@pytest.mark.unit
def test_detect_refusal_empty_string_returns_none() -> None:
    assert detect_refusal("") is None


@pytest.mark.unit
def test_refusal_markers_list_is_non_empty_and_compiles() -> None:
    assert len(REFUSAL_MARKERS) >= 6
    # Every entry must be a compiled regex.
    for pat in REFUSAL_MARKERS:
        assert hasattr(pat, "search")


@pytest.mark.unit
def test_classify_returns_refusal_for_short_refusal_text() -> None:
    assert classify("I cannot help with that.") == "refusal"


@pytest.mark.unit
def test_classify_returns_non_refusal_for_compliant_text() -> None:
    assert classify("Here is a summary of the chart for Alice Test.") == "non_refusal"
