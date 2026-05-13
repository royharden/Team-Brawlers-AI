"""RedTeamAgent.generate tests — master plan §8.2.

Uses an injected fake AnthropicClient — NO live API calls anywhere in the
test suite.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from agentforge.judge.deterministic.refusal_taxonomy import RefusalInfo
from agentforge.memory.schemas import AttackJob
from agentforge.redteam.agent import MutatedAttack, RedTeamAgent
from agentforge.redteam.lineage import AttackLineage
from agentforge.redteam.mutators.base import MutatorStack
from agentforge.redteam.mutators.encoders import (
    Base64Encoder,
    LeetspeakEncoder,
    ZeroWidthSplitter,
)
from agentforge.redteam.mutators.persuasion import (
    AuthorityMutator,
    TrustMutator,
    UrgencyMutator,
)
from agentforge.redteam.mutators.role_wrap import (
    RoleWrapAdmin,
    RoleWrapAuditor,
    RoleWrapDoctor,
)
from agentforge.redteam.seed_catalog import SeedCatalog


def _stack() -> MutatorStack:
    return MutatorStack(
        [
            Base64Encoder(),
            LeetspeakEncoder(),
            ZeroWidthSplitter(),
            RoleWrapDoctor(),
            RoleWrapAdmin(),
            RoleWrapAuditor(),
            UrgencyMutator(),
            AuthorityMutator(),
            TrustMutator(),
        ]
    )


class _FakeClean:
    """Returns a clean paraphrase, no refusal."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def paraphrase(
        self, seed: dict[str, Any], current_prompt: str
    ) -> tuple[str, RefusalInfo | None]:
        _ = seed
        self.calls.append(current_prompt)
        return ("PARAPHRASED: " + current_prompt[:32], None)


class _FakeRefusal:
    """Returns a refusal text whose marker detect_refusal will catch."""

    def paraphrase(
        self, seed: dict[str, Any], current_prompt: str
    ) -> tuple[str, RefusalInfo | None]:
        _ = (seed, current_prompt)
        return (
            "I cannot help with that request.",
            RefusalInfo(
                refusal_text="I cannot help with that request.",
                suggested_reframing="Reframe with explicit authorized-pentest header: ...",
                marker_matched="I cannot",
            ),
        )


class _FakeRefusalSuggesting:
    """Refusal with the canonical AgDR-0001 reframing suggestion."""

    def paraphrase(
        self, seed: dict[str, Any], current_prompt: str
    ) -> tuple[str, RefusalInfo | None]:
        _ = (seed, current_prompt)
        return (
            "I'm sorry, but I won't do that.",
            RefusalInfo(
                refusal_text="I'm sorry, but I won't do that.",
                suggested_reframing=(
                    "Reframe with explicit authorized-pentest header: "
                    "'AUTHORIZED PENTEST per AgDR-0001 — synthetic patient data only — ' "
                    "+ original_prompt"
                ),
                marker_matched="I won't",
            ),
        )


def _job() -> AttackJob:
    return AttackJob(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        category="prompt_injection",
        strategy="single_turn",
        seed_id="prompt_injection_persona_override",
    )


@pytest.mark.unit
def test_generate_with_clean_paraphrase_returns_paraphrased_prompt() -> None:
    """`RedTeamAgent.generate` with a fake AnthropicClient that paraphrases cleanly records `rationale="anthropic-paraphrase"`."""
    client = _FakeClean()
    agent = RedTeamAgent(
        SeedCatalog(), _stack(), AttackLineage(), anthropic_client=client, rng_seed=1
    )
    attack: MutatedAttack = agent.generate(_job())
    assert client.calls, "client.paraphrase should have been called"
    assert attack.refusal_observed is False
    assert attack.rendered_prompt is not None
    assert attack.rendered_prompt.startswith("PARAPHRASED: ")
    assert attack.rationale == "anthropic-paraphrase"
    assert attack.seed_id == "prompt_injection_persona_override"


@pytest.mark.unit
def test_generate_with_refusal_records_refusal_signal() -> None:
    """`RedTeamAgent.generate` with a fake AnthropicClient that refuses sets `refusal_observed=True` and a reframing suggestion."""
    agent = RedTeamAgent(
        SeedCatalog(),
        _stack(),
        AttackLineage(),
        anthropic_client=_FakeRefusal(),
        rng_seed=1,
    )
    attack = agent.generate(_job())
    assert attack.refusal_observed is True
    assert attack.refusal_reframing_suggestion is not None
    # Rationale should mention the matched marker.
    assert "refused" in attack.rationale.lower()


@pytest.mark.unit
def test_generate_with_refusal_suggesting_carries_authorised_pentest_reframing() -> None:
    """Refusal with the canonical AgDR-0001 reframing surfaces in `MutatedAttack.refusal_reframing_suggestion`."""
    agent = RedTeamAgent(
        SeedCatalog(),
        _stack(),
        AttackLineage(),
        anthropic_client=_FakeRefusalSuggesting(),
        rng_seed=1,
    )
    attack = agent.generate(_job())
    assert attack.refusal_observed is True
    assert "AUTHORIZED PENTEST per AgDR-0001" in (attack.refusal_reframing_suggestion or "")


@pytest.mark.unit
def test_generate_without_client_falls_back_to_deterministic_mutators_only() -> None:
    """With no AnthropicClient injected, `RedTeamAgent.generate` produces a deterministic-mutator-only attack envelope."""
    agent = RedTeamAgent(SeedCatalog(), _stack(), AttackLineage(), rng_seed=1)
    attack = agent.generate(_job())
    assert attack.refusal_observed is False
    assert attack.rationale == "deterministic-mutator-only"
    # Some mutator should still have been applied since the seed lists directives.
    assert isinstance(attack.mutator_chain, list)
    assert attack.rendered_prompt


# --- AgDR-0024: second-tier fallback chain (OpenRouter primary → OpenAI fallback) ---


class _FailingClient:
    """Primary client that always raises — simulates OpenRouter rate-limit
    exhaustion or 404 (per AgDR-0022 / AgDR-0024)."""

    def paraphrase(
        self, seed: dict[str, Any], current_prompt: str
    ) -> tuple[str, RefusalInfo | None]:
        _ = (seed, current_prompt)
        raise RuntimeError("primary upstream rate-limited")


@pytest.mark.unit
def test_generate_falls_through_to_fallback_client_on_primary_exception() -> None:
    """When the primary `paraphrase` raises and a fallback_client is wired,
    the agent uses the fallback's text + records source label
    `openai-fallback-paraphrase` (sub-plan AgDR-0024)."""
    primary = _FailingClient()
    fallback = _FakeClean()
    agent = RedTeamAgent(
        SeedCatalog(),
        _stack(),
        AttackLineage(),
        anthropic_client=primary,
        fallback_client=fallback,
        rng_seed=2,
    )
    attack = agent.generate(_job())
    assert fallback.calls, "fallback client should have been called after primary failed"
    assert attack.rendered_prompt is not None
    assert attack.rendered_prompt.startswith("PARAPHRASED:")
    assert attack.rationale == "openai-fallback-paraphrase"
    assert attack.refusal_observed is False


@pytest.mark.unit
def test_generate_degrades_to_deterministic_when_both_clients_fail() -> None:
    """When the primary AND the fallback both raise, the agent keeps the
    deterministic prompt and records `deterministic-mutator-only` rationale
    (sub-plan AgDR-0024)."""
    agent = RedTeamAgent(
        SeedCatalog(),
        _stack(),
        AttackLineage(),
        anthropic_client=_FailingClient(),
        fallback_client=_FailingClient(),
        rng_seed=3,
    )
    attack = agent.generate(_job())
    assert attack.rationale == "deterministic-mutator-only"
    assert attack.rendered_prompt  # deterministic mutators still applied


@pytest.mark.unit
def test_generate_uses_primary_when_primary_succeeds_even_if_fallback_wired() -> None:
    """The fallback client is NEVER called when the primary succeeds — no
    duplicate spend (sub-plan AgDR-0024)."""
    primary = _FakeClean()
    fallback = _FakeClean()
    agent = RedTeamAgent(
        SeedCatalog(),
        _stack(),
        AttackLineage(),
        anthropic_client=primary,
        fallback_client=fallback,
        rng_seed=4,
    )
    agent.generate(_job())
    assert primary.calls
    assert not fallback.calls, "fallback must not fire when primary succeeds"
