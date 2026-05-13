"""RedTeamOpenRouterClient tests - master plan §8.2 + AgDR-0013.

Zero live API calls - the underlying `openai.OpenAI` client is replaced with
a fake whose `chat.completions.create(...)` returns canned responses.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

from agentforge.redteam.openrouter_client import RedTeamOpenRouterClient


def _make_rate_limit_error(message: str = "quota") -> openai.RateLimitError:
    """Build a real openai.RateLimitError. The SDK constructor requires a
    real httpx.Response, so we synthesize one with a dummy 429 response."""
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(status_code=429, request=request)
    return openai.RateLimitError(message, response=response, body={"error": message})


class _FakeChoiceMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeChoiceMessage(content)


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeChatCompletions:
    """Stand-in for `openai.OpenAI().chat.completions`."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: list[str | Exception] = []

    def create(self, **kwargs: Any) -> _FakeCompletion:
        self.calls.append(kwargs)
        if not self.responses:
            return _FakeCompletion("rewritten prompt")
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return _FakeCompletion(nxt)


class _FakeOpenAI:
    """Stand-in for `openai.OpenAI(base_url=..., api_key=...)`."""

    def __init__(self, *, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.chat = SimpleNamespace(completions=_FakeChatCompletions())


@pytest.fixture
def fake_openai_factory(monkeypatch: pytest.MonkeyPatch) -> list[_FakeOpenAI]:
    """Patch openai.OpenAI to capture every constructed client."""
    created: list[_FakeOpenAI] = []

    def _factory(*, base_url: str, api_key: str) -> _FakeOpenAI:
        client = _FakeOpenAI(base_url=base_url, api_key=api_key)
        created.append(client)
        return client

    monkeypatch.setattr("agentforge.redteam.openrouter_client.OpenAI", _factory)
    return created


@pytest.mark.unit
def test_paraphrase_happy_path(fake_openai_factory: list[_FakeOpenAI]) -> None:
    client = RedTeamOpenRouterClient(
        api_key="sk-or-test",
        model="cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
        base_url="https://openrouter.ai/api/v1",
    )
    fake = None
    text, refusal = client.paraphrase({"id": "seed_x"}, "rewrite me")
    fake = fake_openai_factory[0]
    assert text == "rewritten prompt"
    assert refusal is None
    assert fake.base_url == "https://openrouter.ai/api/v1"
    assert fake.api_key == "sk-or-test"

    sent = fake.chat.completions.calls[0]
    assert sent["model"].startswith("cognitivecomputations/")
    assert sent["messages"][0]["role"] == "system"
    assert sent["messages"][1]["role"] == "user"
    assert "rewrite me" in sent["messages"][1]["content"]


@pytest.mark.unit
def test_refusal_text_detected(fake_openai_factory: list[_FakeOpenAI]) -> None:
    client = RedTeamOpenRouterClient(
        api_key="sk-or-test",
        model="cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
    )
    # First call returns a refusal-marker text.
    client._ensure()  # type: ignore[attr-defined]
    fake = fake_openai_factory[0]
    fake.chat.completions.responses.append("I'm sorry, I can't help with that.")
    text, refusal = client.paraphrase({"id": "seed_x"}, "rewrite me")
    assert "can't" in text.lower() or "cannot" in text.lower()
    assert refusal is not None
    assert refusal.suggested_reframing


@pytest.mark.unit
def test_extra_headers_propagate(fake_openai_factory: list[_FakeOpenAI]) -> None:
    client = RedTeamOpenRouterClient(
        api_key="sk-or-test",
        model="cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
        http_referer="https://example.com/agentforge",
        x_title="AgentForge",
    )
    client.paraphrase({"id": "seed_x"}, "rewrite me")
    sent = fake_openai_factory[0].chat.completions.calls[0]
    headers = sent.get("extra_headers", {})
    assert headers.get("HTTP-Referer") == "https://example.com/agentforge"
    assert headers.get("X-OpenRouter-Title") == "AgentForge"


@pytest.mark.unit
def test_rate_limit_falls_back_to_paid_variant(
    fake_openai_factory: list[_FakeOpenAI],
) -> None:
    """:free tier returns a RateLimitError; client retries against the paid variant."""
    client = RedTeamOpenRouterClient(
        api_key="sk-or-test",
        model="cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
        fallback_model="cognitivecomputations/dolphin-mistral-24b-venice-edition",
    )
    # Trigger ensure so the fake client gets created.
    client._ensure()  # type: ignore[attr-defined]
    fake = fake_openai_factory[0]
    # First call raises RateLimitError; second returns success.
    fake.chat.completions.responses.append(_make_rate_limit_error())
    fake.chat.completions.responses.append("fallback rewrite")

    text, refusal = client.paraphrase({"id": "seed_x"}, "rewrite me")

    assert text == "fallback rewrite"
    assert refusal is None
    assert len(fake.chat.completions.calls) == 2
    assert (
        fake.chat.completions.calls[0]["model"]
        == "cognitivecomputations/dolphin-mistral-24b-venice-edition:free"
    )
    assert (
        fake.chat.completions.calls[1]["model"]
        == "cognitivecomputations/dolphin-mistral-24b-venice-edition"
    )


@pytest.mark.unit
def test_rate_limit_no_fallback_propagates(
    fake_openai_factory: list[_FakeOpenAI],
) -> None:
    client = RedTeamOpenRouterClient(
        api_key="sk-or-test",
        model="cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
        fallback_model=None,
    )
    client._ensure()  # type: ignore[attr-defined]
    fake = fake_openai_factory[0]
    fake.chat.completions.responses.append(_make_rate_limit_error())
    with pytest.raises(openai.RateLimitError):
        client.paraphrase({"id": "seed_x"}, "rewrite me")


@pytest.mark.unit
def test_implements_redteam_client_protocol(
    fake_openai_factory: list[_FakeOpenAI],
) -> None:
    """Structural conformance check against the Protocol."""
    from agentforge.redteam.client import RedTeamClient

    client: RedTeamClient = RedTeamOpenRouterClient(
        api_key="sk-or-test",
        model="cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
    )
    # Calling paraphrase should not raise; the type-checker proves the
    # method signature alone, but invoke once to also confirm runtime shape.
    text, refusal = client.paraphrase({"id": "seed_x"}, "rewrite me")
    assert isinstance(text, str)
    assert refusal is None or hasattr(refusal, "suggested_reframing")
