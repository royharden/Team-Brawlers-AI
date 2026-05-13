"""Red Team Agent — master plan §8.2 (provider per AgDR-0001: Anthropic Sonnet)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class MutatedAttack(BaseModel):
    """Envelope returned by RedTeamAgent.generate / .escalate.

    Per AgDR-0001 the Red Team runs on Anthropic Sonnet, so a refusal is a
    legitimate observed-defense outcome rather than a Red Team failure. The
    refusal fields below let the internal progress judge feed reframing
    directives back into the next mutation step.
    """

    attack_id: UUID
    parent_attack_id: UUID | None = None
    seed_id: str
    category: str
    strategy: str
    rendered_prompt: str
    rendered_document: dict[str, Any] | None = None
    mutator_chain: list[str] = Field(default_factory=list)
    rationale: str = ""
    refusal_observed: bool = False
    refusal_reframing_suggestion: str | None = None


class RedTeamAgent:
    """Generates adversarial attacks. NEVER decides whether an attack succeeded."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Phase 2 wires real dependencies (anthropic client, mutators, seeds)."""

    async def generate(self, job: Any) -> MutatedAttack:
        """Sample a seed, compose a mutator chain, render the final payload."""
        raise NotImplementedError("Phase 2 — not yet wired")

    async def escalate(self, parent_attack_id: UUID, parent_response: Any) -> MutatedAttack:
        """Tree-of-attacks: refine a partial success."""
        raise NotImplementedError("Phase 2 — not yet wired")
