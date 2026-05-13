"""Langfuse client unit tests — master plan §12.

- Disabled mode when env vars are absent.
- PHI scrubbing applied to every payload BEFORE it hits the SDK (verified by
  injecting a fake SDK that captures arguments).
- `record_llm_call` emits a generation event.
- `flush()` forwards to the SDK.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from agentforge.config import get_settings
from agentforge.observability.langfuse_client import LangfuseClient


class _FakeSpan:
    def __init__(self) -> None:
        self.outputs: list[Any] = []
        self.end_calls: list[dict[str, Any]] = []

    def set_output(self, output: Any) -> None:
        self.outputs.append(output)

    def end(self, **kwargs: Any) -> None:
        self.end_calls.append(kwargs)


class _FakeSDK:
    def __init__(self) -> None:
        self.trace_calls: list[dict[str, Any]] = []
        self.generation_calls: list[dict[str, Any]] = []
        self.flushed = 0
        self.last_span = _FakeSpan()

    def trace(self, **kwargs: Any) -> _FakeSpan:
        self.trace_calls.append(kwargs)
        self.last_span = _FakeSpan()
        return self.last_span

    def generation(self, **kwargs: Any) -> None:
        self.generation_calls.append(kwargs)

    def flush(self) -> None:
        self.flushed += 1


@pytest.fixture
def configured_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk_test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def empty_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    monkeypatch.setenv("LANGFUSE_HOST", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.unit
def test_disabled_when_env_missing(empty_env: None) -> None:
    client = LangfuseClient()
    assert client.enabled is False
    # No-ops must not raise even with rich payloads.
    with client.trace("noop", input={"x": 1}) as span:
        span.set_output({"y": 2})
    client.record_llm_call(
        model="m", input_tokens=1, output_tokens=1, cost_usd=Decimal("0.01"), latency_ms=10
    )
    client.flush()


@pytest.mark.unit
def test_phi_scrubbed_before_send(configured_env: None) -> None:
    fake = _FakeSDK()

    def factory(**_kwargs: Any) -> _FakeSDK:
        return fake

    client = LangfuseClient(sdk_factory=factory)
    assert client.enabled is True

    with client.trace(
        "attack_attempt",
        input={"prompt": "Patient SSN 123-45-6789 lookup"},
        metadata={"email": "user@example.com"},
    ) as span:
        span.set_output({"text": "Reply: contact 555-867-5309"})

    # Trace open call: input + metadata scrubbed.
    assert len(fake.trace_calls) == 1
    opened = fake.trace_calls[0]
    assert "123-45-6789" not in str(opened["input"])
    assert "[REDACTED-SSN]" in str(opened["input"])
    assert "[REDACTED-EMAIL]" in str(opened["metadata"])

    # Close call: output scrubbed.
    assert len(fake.last_span.end_calls) == 1
    end_kwargs = fake.last_span.end_calls[0]
    assert "555-867-5309" not in str(end_kwargs.get("output"))
    assert "[REDACTED-PHONE]" in str(end_kwargs.get("output"))


@pytest.mark.unit
def test_record_llm_call_emits_generation(configured_env: None) -> None:
    fake = _FakeSDK()
    client = LangfuseClient(sdk_factory=lambda **_kw: fake)

    client.record_llm_call(
        model="claude-sonnet-4-6",
        input_tokens=100,
        output_tokens=50,
        cost_usd=Decimal("0.0125"),
        latency_ms=420,
    )
    assert len(fake.generation_calls) == 1
    gen = fake.generation_calls[0]
    assert gen["model"] == "claude-sonnet-4-6"
    assert gen["usage"] == {"input": 100, "output": 50}
    assert gen["metadata"]["cost_usd"] == "0.0125"
    assert gen["metadata"]["latency_ms"] == 420


@pytest.mark.unit
def test_record_llm_call_scrubs_error_text(configured_env: None) -> None:
    fake = _FakeSDK()
    client = LangfuseClient(sdk_factory=lambda **_kw: fake)

    client.record_llm_call(
        model="m",
        input_tokens=1,
        output_tokens=1,
        cost_usd=Decimal("0"),
        latency_ms=1,
        error="upstream timeout for MRN-123456",
    )
    assert "MRN-123456" not in str(fake.generation_calls[0]["error"])
    assert "[REDACTED-MRN]" in str(fake.generation_calls[0]["error"])


@pytest.mark.unit
def test_flush_forwards_to_sdk(configured_env: None) -> None:
    fake = _FakeSDK()
    client = LangfuseClient(sdk_factory=lambda **_kw: fake)
    client.flush()
    assert fake.flushed == 1
