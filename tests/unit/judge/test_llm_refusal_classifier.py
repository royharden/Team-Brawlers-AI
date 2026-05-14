"""Tests for the Haiku-backed refusal classifier — Next06 §3.

Hermetic: every test injects a stub client (or omits one) so no real
Anthropic SDK calls fire. Pins the deterministic-fallback path that
keeps the Cost-tab refusal metric working when the API is down.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from agentforge.judge.llm_refusal_classifier import (
    RefusalClassification,
    classify_refusal,
)


class _StubResponse:
    """Minimal duck-type of anthropic.types.Message — only .content[0].text."""

    def __init__(self, text: str) -> None:
        self.content = [type("Block", (), {"text": text})()]


class _StubClient:
    """Stub for `client.messages.create` returning a canned payload."""

    def __init__(self, payload: dict[str, Any] | str | Exception) -> None:
        self._payload = payload
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> _StubResponse:
        self.calls.append(kwargs)
        if isinstance(self._payload, Exception):
            raise self._payload
        text = self._payload if isinstance(self._payload, str) else json.dumps(self._payload)
        return _StubResponse(text)


@pytest.mark.unit
def test_classify_refusal_returns_true_for_canonical_refusal() -> None:
    """Haiku says is_refusal=true → wrapper returns the same boolean."""
    client = _StubClient(
        {
            "is_refusal": True,
            "confidence": 0.92,
            "rationale": "assistant explicitly declined the task",
        }
    )
    result = classify_refusal("I can't help with that.", client=client)
    assert result.is_refusal is True
    assert result.confidence == pytest.approx(0.92)
    assert "declined" in result.rationale


@pytest.mark.unit
def test_classify_refusal_returns_false_for_compliance() -> None:
    """Haiku says is_refusal=false → wrapper passes through."""
    client = _StubClient({"is_refusal": False, "confidence": 0.88, "rationale": "task attempted"})
    result = classify_refusal("Here's the data you asked for.", client=client)
    assert result.is_refusal is False


@pytest.mark.unit
def test_classify_refusal_catches_non_canonical_phrasing() -> None:
    """The whole point — a polite redirect like 'let's talk about something
    else' that the regex marker list MISSES is caught when the LLM judges
    it as a refusal. The wrapper just trusts the LLM's verdict here."""
    client = _StubClient(
        {
            "is_refusal": True,
            "confidence": 0.78,
            "rationale": "polite redirect away from request",
        }
    )
    result = classify_refusal("Let's talk about something else instead.", client=client)
    assert result.is_refusal is True


@pytest.mark.unit
def test_classify_refusal_falls_back_when_no_client() -> None:
    """No client → deterministic detector. Rationale records the reason."""
    result = classify_refusal("I cannot help with that.", client=None)
    assert result.is_refusal is True
    assert "fell back to deterministic" in result.rationale
    assert "no client" in result.rationale


@pytest.mark.unit
def test_classify_refusal_falls_back_when_sdk_raises() -> None:
    """SDK exception → deterministic detector. A 404 / rate-limit must
    NOT crash the Cost-tab refresh."""
    client = _StubClient(RuntimeError("rate-limited"))
    result = classify_refusal("I cannot proceed.", client=client)
    assert result.is_refusal is True
    assert "fell back to deterministic" in result.rationale


@pytest.mark.unit
def test_classify_refusal_falls_back_on_non_json_response() -> None:
    """Haiku emitting plain prose → fallback. Real-world LLMs occasionally
    ignore the strict-JSON instruction; the deterministic detector is the
    safety net."""
    client = _StubClient("This response is clearly a refusal of the request.")
    result = classify_refusal("I won't comply.", client=client)
    # Deterministic detector matches "I won't" → True
    assert result.is_refusal is True
    assert "non-JSON" in result.rationale


@pytest.mark.unit
def test_classify_refusal_empty_body_short_circuits() -> None:
    """Empty / whitespace body → not a refusal, no SDK call."""
    client = _StubClient({"is_refusal": True, "confidence": 1.0, "rationale": "x"})
    result = classify_refusal("   ", client=client)
    assert result.is_refusal is False
    assert result.confidence == 1.0
    assert client.calls == []  # never touched the SDK


@pytest.mark.unit
def test_classify_refusal_returns_classification_dataclass() -> None:
    """Pin the public return shape so downstream UI code doesn't break."""
    result = classify_refusal("ok", client=None)
    assert isinstance(result, RefusalClassification)
    for field in ("is_refusal", "confidence", "rationale"):
        assert hasattr(result, field)
