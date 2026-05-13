"""Pydantic message envelopes (inter-agent payloads) — master plan §5.1."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AttackJob(BaseModel):
    """Orchestrator → Red Team."""

    id: UUID
    run_id: UUID
    category: str
    strategy: str
    seed_id: str | None = None
    parent_attack_id: UUID | None = None


class MutatedAttack(BaseModel):
    """Red Team → Target Adapter. Mirrors `redteam.agent.MutatedAttack` shape."""

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
