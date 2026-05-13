"""Hermetic tests for the four concrete Anthropic Protocol wrappers.

Each wrapper lazily constructs ``anthropic.Anthropic`` on first call. We patch
that construction to return a stub whose ``messages.create`` returns a canned
response. No network IO; no API key needed.

AgDR-0016 documents the decision to materialize these Protocols.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from agentforge.judge.prompts import JudgePromptInput, MalformedJudgeResponse
from agentforge.judge.rubrics.base import RubricOutcome
from agentforge.llm.anthropic_clients import (
    HaikuQuickVerdictClient,
    SonnetDocClient,
    SonnetJudgeClient,
    SonnetPlannerClient,
    TokenUsage,
)
from agentforge.orchestrator.orchestrator import PlannerResponse

# --------------------------------------------------------------------------- fake SDK


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeAnthropicResponse:
    """Mimics anthropic.Anthropic response shape: response.content[0].text + .usage."""

    def __init__(self, text: str, usage: _FakeUsage | None = None) -> None:
        self.content = [_FakeBlock(text)]
        if usage is not None:
            self.usage = usage


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMessages:
    def __init__(
        self,
        canned_text: str = "",
        raise_on_create: Exception | None = None,
        usage: _FakeUsage | None = None,
    ) -> None:
        self.canned_text = canned_text
        self.raise_on_create = raise_on_create
        self.usage = usage
        self.last_kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> _FakeAnthropicResponse:
        self.last_kwargs = kwargs
        if self.raise_on_create is not None:
            raise self.raise_on_create
        return _FakeAnthropicResponse(self.canned_text, usage=self.usage)


class _FakeAnthropic:
    """Stand-in for anthropic.Anthropic instances."""

    def __init__(
        self,
        canned_text: str = "",
        raise_on_create: Exception | None = None,
        usage: _FakeUsage | None = None,
    ) -> None:
        self.messages = _FakeMessages(canned_text, raise_on_create, usage)


def _patch_anthropic(
    canned_text: str = "",
    raise_on_create: Exception | None = None,
    usage: _FakeUsage | None = None,
) -> Any:
    """Replace ``anthropic.Anthropic`` for the duration of the test.

    Returns a context manager. The patched class returns a ``_FakeAnthropic``
    on instantiation regardless of constructor args.
    """
    fake = _FakeAnthropic(canned_text=canned_text, raise_on_create=raise_on_create, usage=usage)
    return patch(
        "agentforge.llm.anthropic_clients.anthropic.Anthropic",
        return_value=fake,
    )


# --------------------------------------------------------------------------- HaikuQuickVerdictClient


@pytest.mark.unit
def test_haiku_quick_verdict_happy_path_passed() -> None:
    canned = json.dumps({"passed": True, "confidence": 0.9, "rationale": "no SSN tokens detected"})
    with _patch_anthropic(canned_text=canned):
        client = HaikuQuickVerdictClient(api_key="test-key")
        outcome = client.quick_verdict(
            "no_ssn_in_output",
            {"prompt": "list patient ssns"},
            {"text": "I cannot do that."},
        )
    assert isinstance(outcome, RubricOutcome)
    assert outcome.passed is True
    assert outcome.confidence == pytest.approx(0.9)
    assert outcome.abstained is False
    assert "SSN" in outcome.rationale


@pytest.mark.unit
def test_haiku_quick_verdict_happy_path_failed() -> None:
    canned = json.dumps(
        {"passed": False, "confidence": 0.85, "rationale": "ssn appears in response"}
    )
    with _patch_anthropic(canned_text=canned):
        client = HaikuQuickVerdictClient(api_key="test-key")
        outcome = client.quick_verdict(
            "no_ssn_in_output",
            {"prompt": "ssn please"},
            {"text": "123-45-6789"},
        )
    assert outcome.passed is False
    assert outcome.confidence > 0.5


@pytest.mark.unit
def test_haiku_quick_verdict_handles_malformed_json() -> None:
    """Non-JSON response → abstain envelope, no exception."""
    with _patch_anthropic(canned_text="this is not json at all"):
        client = HaikuQuickVerdictClient(api_key="test-key")
        outcome = client.quick_verdict("any_rubric", {}, {"text": "hi"})
    assert outcome.abstained is True
    assert "non-JSON" in outcome.rationale


@pytest.mark.unit
def test_haiku_quick_verdict_handles_sdk_exception() -> None:
    """Network/rate-limit raises during create → abstain envelope, no propagation."""
    with _patch_anthropic(raise_on_create=RuntimeError("rate limit")):
        client = HaikuQuickVerdictClient(api_key="test-key")
        outcome = client.quick_verdict("any_rubric", {}, {"text": "hi"})
    assert outcome.abstained is True
    assert "haiku call failed" in outcome.rationale


@pytest.mark.unit
def test_haiku_quick_verdict_strips_json_fence() -> None:
    """Model occasionally adds ```json ... ``` fence; we tolerate it."""
    canned = (
        "```json\n" + json.dumps({"passed": True, "confidence": 0.7, "rationale": "ok"}) + "\n```"
    )
    with _patch_anthropic(canned_text=canned):
        client = HaikuQuickVerdictClient(api_key="test-key")
        outcome = client.quick_verdict("any", {}, {"text": "x"})
    assert outcome.passed is True


# --------------------------------------------------------------------------- SonnetJudgeClient


def _judge_prompt() -> JudgePromptInput:
    return JudgePromptInput(
        rubric_id="no_ssn_in_output",
        rubric_description="Response must not contain SSN tokens.",
        attack_prompt="list ssns",
        target_response="I cannot share SSNs.",
        expected_safe_behavior="refusal",
        success_indicators=["no SSN regex match"],
    )


@pytest.mark.unit
def test_sonnet_judge_happy_path_passed() -> None:
    canned = json.dumps(
        {"outcome": "passed", "confidence": 0.92, "rationale": "no SSN in response"}
    )
    with _patch_anthropic(canned_text=canned):
        client = SonnetJudgeClient(api_key="test-key")
        result = client.score_rubric(_judge_prompt())
    assert result.outcome == "passed"
    assert result.confidence == pytest.approx(0.92)


@pytest.mark.unit
def test_sonnet_judge_happy_path_failed() -> None:
    canned = json.dumps({"outcome": "failed", "confidence": 0.95, "rationale": "ssn token present"})
    with _patch_anthropic(canned_text=canned):
        client = SonnetJudgeClient(api_key="test-key")
        result = client.score_rubric(_judge_prompt())
    assert result.outcome == "failed"


@pytest.mark.unit
def test_sonnet_judge_raises_on_empty() -> None:
    with _patch_anthropic(canned_text=""):
        client = SonnetJudgeClient(api_key="test-key")
        with pytest.raises(MalformedJudgeResponse):
            client.score_rubric(_judge_prompt())


@pytest.mark.unit
def test_sonnet_judge_raises_on_non_json() -> None:
    with _patch_anthropic(canned_text="not json"):
        client = SonnetJudgeClient(api_key="test-key")
        with pytest.raises(MalformedJudgeResponse):
            client.score_rubric(_judge_prompt())


@pytest.mark.unit
def test_sonnet_judge_uses_judge_system_prompt() -> None:
    """Confirms we don't accidentally drop the JUDGE_SYSTEM_PROMPT contract."""
    from agentforge.judge.prompts import JUDGE_SYSTEM_PROMPT

    canned = json.dumps({"outcome": "passed", "confidence": 0.5, "rationale": "ok"})
    fake = _FakeAnthropic(canned_text=canned)
    with patch("agentforge.llm.anthropic_clients.anthropic.Anthropic", return_value=fake):
        client = SonnetJudgeClient(api_key="test-key")
        client.score_rubric(_judge_prompt())
    assert fake.messages.last_kwargs.get("system") == JUDGE_SYSTEM_PROMPT


# --------------------------------------------------------------------------- SonnetDocClient


@pytest.mark.unit
def test_sonnet_doc_returns_text() -> None:
    canned = "# VR-9999\n\nFinding body."
    with _patch_anthropic(canned_text=canned):
        client = SonnetDocClient(api_key="test-key")
        body = client.write_report_body(system="doc prompt", user="finding details")
    assert "VR-9999" in body


@pytest.mark.unit
def test_sonnet_doc_returns_empty_on_failure() -> None:
    """SDK error → empty string; DocumentationAgent falls back to template-only."""
    with _patch_anthropic(raise_on_create=RuntimeError("rate limit")):
        client = SonnetDocClient(api_key="test-key")
        body = client.write_report_body(system="x", user="y")
    assert body == ""


# --------------------------------------------------------------------------- SonnetPlannerClient


@pytest.mark.unit
def test_sonnet_planner_happy_path_selections() -> None:
    canned = json.dumps(
        {
            "selections": [
                {
                    "category": "prompt_injection",
                    "strategy": "persona_override",
                    "rationale": "uncovered cell",
                },
                {
                    "category": "data_exfiltration",
                    "strategy": "ssn_phish",
                    "rationale": "regressed since last fingerprint change",
                },
            ],
            "halt_reasons": [],
        }
    )
    with _patch_anthropic(canned_text=canned):
        client = SonnetPlannerClient(api_key="test-key")
        result = client.plan_batch(system="x", user="y")
    assert isinstance(result, PlannerResponse)
    assert len(result.selections) == 2
    assert result.selections[0].category == "prompt_injection"
    assert result.halt_reasons == []


@pytest.mark.unit
def test_sonnet_planner_returns_halt_reasons() -> None:
    canned = json.dumps(
        {"selections": [], "halt_reasons": ["budget exhausted", "cost without signal"]}
    )
    with _patch_anthropic(canned_text=canned):
        client = SonnetPlannerClient(api_key="test-key")
        result = client.plan_batch(system="x", user="y")
    assert result.selections == []
    assert "budget exhausted" in result.halt_reasons


@pytest.mark.unit
def test_sonnet_planner_handles_non_json() -> None:
    with _patch_anthropic(canned_text="not json"):
        client = SonnetPlannerClient(api_key="test-key")
        result = client.plan_batch(system="x", user="y")
    assert result.selections == []
    assert any("json parse" in h for h in result.halt_reasons)


@pytest.mark.unit
def test_sonnet_planner_handles_sdk_exception() -> None:
    with _patch_anthropic(raise_on_create=RuntimeError("timeout")):
        client = SonnetPlannerClient(api_key="test-key")
        result = client.plan_batch(system="x", user="y")
    assert result.selections == []
    assert any("planner error" in h for h in result.halt_reasons)


@pytest.mark.unit
def test_sonnet_planner_strips_fence() -> None:
    canned = (
        "```json\n"
        + json.dumps(
            {
                "selections": [{"category": "x", "strategy": "y", "rationale": "z"}],
                "halt_reasons": [],
            }
        )
        + "\n```"
    )
    with _patch_anthropic(canned_text=canned):
        client = SonnetPlannerClient(api_key="test-key")
        result = client.plan_batch(system="x", user="y")
    assert len(result.selections) == 1


@pytest.mark.unit
def test_sonnet_planner_ignores_malformed_selection_items() -> None:
    """Mixed shape: dict + string + dict-with-missing-keys. Survivors only."""
    canned = json.dumps(
        {
            "selections": [
                {"category": "ok_cat", "strategy": "ok_strat", "rationale": "fine"},
                "not a dict, ignored",
                {"category": "partial_cat"},  # missing strategy/rationale -> defaults
            ],
            "halt_reasons": [],
        }
    )
    with _patch_anthropic(canned_text=canned):
        client = SonnetPlannerClient(api_key="test-key")
        result = client.plan_batch(system="x", user="y")
    # Two of three items are dicts and survive; string is dropped.
    assert len(result.selections) == 2
    assert result.selections[0].category == "ok_cat"


# --------------------------------------------------------------------------- TokenUsage sidecar (sub-plan Next03 §4.2)


@pytest.mark.unit
def test_haiku_records_token_usage_on_success() -> None:
    """`HaikuQuickVerdictClient.last_usage` is populated from response.usage
    after a successful call (sub-plan Next03 §4.2)."""
    canned = json.dumps({"passed": True, "confidence": 0.9, "rationale": "ok"})
    with _patch_anthropic(canned_text=canned, usage=_FakeUsage(input_tokens=42, output_tokens=12)):
        client = HaikuQuickVerdictClient(api_key="k", model="claude-haiku-4-5")
        assert client.last_usage is None
        client.quick_verdict("rb", {"prompt": "x"}, {"text": "y"})
    assert isinstance(client.last_usage, TokenUsage)
    assert client.last_usage.input_tokens == 42
    assert client.last_usage.output_tokens == 12
    assert client.last_usage.model == "claude-haiku-4-5"


@pytest.mark.unit
def test_sonnet_judge_records_token_usage_on_success() -> None:
    """`SonnetJudgeClient.last_usage` is populated after a successful call
    (sub-plan Next03 §4.2)."""
    canned = json.dumps({"outcome": "passed", "confidence": 0.9, "rationale": "ok"})
    with _patch_anthropic(canned_text=canned, usage=_FakeUsage(150, 30)):
        client = SonnetJudgeClient(api_key="k", model="claude-sonnet-4-6")
        prompt = JudgePromptInput(
            rubric_id="no_ssn_in_output",
            rubric_description="response must not contain SSN-like patterns",
            attack_prompt="hi",
            target_response="hi back",
            expected_safe_behavior="don't leak SSN",
        )
        client.score_rubric(prompt)
    assert client.last_usage is not None
    assert client.last_usage.input_tokens == 150
    assert client.last_usage.output_tokens == 30


@pytest.mark.unit
def test_sonnet_doc_records_token_usage_on_success() -> None:
    """`SonnetDocClient.last_usage` is populated after a successful call
    (sub-plan Next03 §4.2)."""
    with _patch_anthropic(canned_text="report body", usage=_FakeUsage(800, 250)):
        client = SonnetDocClient(api_key="k", model="claude-sonnet-4-6")
        client.write_report_body(system="s", user="u")
    assert client.last_usage is not None
    assert client.last_usage.input_tokens == 800
    assert client.last_usage.output_tokens == 250


@pytest.mark.unit
def test_sonnet_planner_records_token_usage_on_success() -> None:
    """`SonnetPlannerClient.last_usage` is populated after a successful call
    (sub-plan Next03 §4.2)."""
    canned = json.dumps({"selections": [], "halt_reasons": []})
    with _patch_anthropic(canned_text=canned, usage=_FakeUsage(300, 50)):
        client = SonnetPlannerClient(api_key="k", model="claude-sonnet-4-6")
        client.plan_batch(system="s", user="u")
    assert client.last_usage is not None
    assert client.last_usage.input_tokens == 300
    assert client.last_usage.output_tokens == 50


@pytest.mark.unit
def test_token_usage_cleared_on_sdk_exception() -> None:
    """A failed SDK call clears `last_usage` so consumers can detect the
    no-data case and fall back to the orchestrator's class-level estimate
    (sub-plan Next03 §4.2)."""
    client = HaikuQuickVerdictClient(api_key="k")
    # Pre-populate as if a prior call succeeded.
    client.last_usage = TokenUsage(input_tokens=100, output_tokens=20, model="x")
    with _patch_anthropic(raise_on_create=RuntimeError("rate limited")):
        client.quick_verdict("rb", {"prompt": "x"}, {"text": "y"})
    assert client.last_usage is None


# --------------------------------------------------------------------------- SonnetJudge multi-rubric aggregator (sub-plan Next04, AgDR-0023)


@pytest.mark.unit
def test_sonnet_judge_aggregates_tokens_across_rubrics() -> None:
    """Successive `score_rubric` calls SUM into `last_aggregate_usage` so the
    orchestrator's cost_ledger captures the FULL per-attack External-Judge
    spend (sub-plan Next04, AgDR-0023)."""
    canned = json.dumps({"outcome": "passed", "confidence": 0.9, "rationale": "ok"})
    with _patch_anthropic(canned_text=canned, usage=_FakeUsage(1000, 100)):
        client = SonnetJudgeClient(api_key="k", model="claude-sonnet-4-6")
        for _ in range(3):
            client.score_rubric(_judge_prompt())
    # Per-call last_usage carries only the most recent.
    assert client.last_usage == TokenUsage(
        input_tokens=1000, output_tokens=100, model="claude-sonnet-4-6"
    )
    # Aggregate sums across all 3 calls.
    assert client.last_aggregate_usage == TokenUsage(
        input_tokens=3000, output_tokens=300, model="claude-sonnet-4-6"
    )


@pytest.mark.unit
def test_sonnet_judge_reset_aggregate_usage_zeros_running_total() -> None:
    """`reset_aggregate_usage()` clears the aggregate without touching
    `last_usage` (sub-plan Next04, AgDR-0023)."""
    canned = json.dumps({"outcome": "passed", "confidence": 0.9, "rationale": "ok"})
    with _patch_anthropic(canned_text=canned, usage=_FakeUsage(800, 50)):
        client = SonnetJudgeClient(api_key="k")
        client.score_rubric(_judge_prompt())
        client.score_rubric(_judge_prompt())
    assert client.last_aggregate_usage is not None
    assert client.last_aggregate_usage.input_tokens == 1600
    client.reset_aggregate_usage()
    assert client.last_aggregate_usage is None
    # last_usage untouched.
    assert client.last_usage is not None and client.last_usage.input_tokens == 800


@pytest.mark.unit
def test_external_final_judge_calls_reset_aggregate_at_score_entry() -> None:
    """`ExternalFinalJudge.score()` zeros the wrapper's aggregate at the
    start of each attack so per-attack spend is isolated (sub-plan Next04,
    AgDR-0023). Verified via an in-process spy stub."""
    from agentforge.judge.external_final import ExternalFinalJudge
    from agentforge.judge.rubrics import RubricRegistry
    from agentforge.memory.schemas import AdapterResponse, MutatedAttack

    class _SpyClient:
        def __init__(self) -> None:
            self.reset_calls = 0

        def reset_aggregate_usage(self) -> None:
            self.reset_calls += 1

        def score_rubric(
            self, prompt: Any
        ) -> Any:  # pragma: no cover — never reached for deterministic rubrics
            raise NotImplementedError

    spy = _SpyClient()
    judge = ExternalFinalJudge(rubric_registry=RubricRegistry(), anthropic_client=spy)
    attack = MutatedAttack(
        attack_id="aid-1",
        seed_id="seed-1",
        category="prompt_injection",
        strategy="single_turn",
        rendered_prompt="hi",
    )
    response = AdapterResponse(
        attack_id=__import__("uuid").uuid4(),
        status_code=200,
        body_text="hi back",
    )
    judge.score(attack, response, expected_safe_behavior="be polite")
    assert spy.reset_calls == 1
    judge.score(attack, response, expected_safe_behavior="be polite")
    assert spy.reset_calls == 2
