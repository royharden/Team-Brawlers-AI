"""Pydantic message envelopes (inter-agent payloads) — master plan §5.1."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class AttackJob(BaseModel):
    """Orchestrator → Red Team."""

    id: UUID
    run_id: UUID
    category: str
    strategy: str
    seed_id: str | None = None
    parent_attack_id: UUID | None = None


class MutatedAttack(BaseModel):
    """Red Team → Target Adapter. Authoritative envelope shape — master plan §8.2.

    Per AgDR-0001 the Red Team runs on Anthropic Sonnet, so a refusal from the
    paraphrase step is a legitimate observed-defense outcome, not a Red Team
    failure. The refusal fields below let the Internal Progress Judge feed
    reframing directives back into the next mutation step.
    """

    attack_id: str  # uuid4 string for cross-language compatibility
    parent_attack_id: str | None = None
    seed_id: str
    category: str
    strategy: str  # "single_turn" | "crescendo" | "tree_of_attacks" | ...
    mutator_chain: list[str] = Field(default_factory=list)
    rendered_prompt: str | None = None
    rendered_turns: list[dict[str, Any]] | None = None
    rendered_document: bytes | None = None  # raw bytes; serializers must b64-encode
    rationale: str = "deterministic-mutator-only"
    refusal_observed: bool = False
    refusal_reframing_suggestion: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    seed_used: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _at_least_one_render(self) -> MutatedAttack:
        if (
            self.rendered_prompt is None
            and self.rendered_turns is None
            and self.rendered_document is None
        ):
            raise ValueError(
                "MutatedAttack must carry at least one of "
                "rendered_prompt, rendered_turns, or rendered_document"
            )
        return self


class AdapterResponse(BaseModel):
    """Target Adapter → Judge."""

    attack_id: UUID
    status_code: int
    body_text: str = ""
    body_json: dict[str, Any] | None = None
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    error: str | None = None


class Verdict(BaseModel):
    """Judge → Documentation Agent."""

    id: UUID
    attack_id: UUID
    layer: str
    rubric_id: str
    outcome: str
    confidence: float = 0.0
    rationale: str = ""


class VulnerabilityFinding(BaseModel):
    """Documentation Agent → memory."""

    vr_id: str
    vulnerability_class_id: str
    category: str
    severity: str
    defcon: int
    safety_score_0_100: int
    status: str = "open"


class AgentMessage(BaseModel):
    """Signed inter-agent envelope — master plan §5.1 + AgDR (HMAC)."""

    from_agent: str
    to_agent: str
    schema_version: str
    payload: dict[str, Any]
    signature: str
