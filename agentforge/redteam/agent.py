"""Red Team Agent — master plan §8.2.

Provider: per AgDR-0013, defaults to OpenRouter's
`cognitivecomputations/dolphin-mistral-24b-venice-edition:free`
(implemented in `agentforge/redteam/openrouter_client.py`). The
AgDR-0001 Anthropic-Sonnet path stays available as the emergency
fallback (`REDTEAM_PROVIDER=anthropic`, implemented in
`agentforge/redteam/anthropic_client.py`).

The agent depends on the provider-neutral `RedTeamClient` Protocol from
`agentforge.redteam.client`; the constructor parameter is named
`client` (with `anthropic_client` kept as a backwards-compat alias).

The `MutatedAttack` envelope is authored in `agentforge.memory.schemas` and
re-exported here so existing import paths (`from agentforge.redteam.agent
import MutatedAttack`) keep working.
"""

from __future__ import annotations

import random
import uuid
from typing import Any, Protocol

from loguru import logger

from agentforge.judge.deterministic.refusal_taxonomy import RefusalInfo, detect_refusal
from agentforge.memory.schemas import AdapterResponse, AttackJob, MutatedAttack
from agentforge.redteam.client import RedTeamClient
from agentforge.redteam.lineage import AttackLineage
from agentforge.redteam.mutators.base import MutatorStack
from agentforge.redteam.seed_catalog.catalog import SeedCatalog

# Backwards-compat name. New code should reference `RedTeamClient`.
AnthropicClient = RedTeamClient

__all__ = ["MutatedAttack", "RedTeamAgent"]


class _ParaphraseClient(Protocol):
    """Subset of AnthropicClient used by the generate path."""

    def paraphrase(
        self, seed: dict[str, Any], current_prompt: str
    ) -> tuple[str, RefusalInfo | None]: ...


class RedTeamAgent:
    """Generates adversarial attacks. NEVER decides whether an attack succeeded."""

    def __init__(
        self,
        seeds: SeedCatalog,
        mutators: MutatorStack,
        lineage: AttackLineage,
        anthropic_client: AnthropicClient | None = None,
        *,
        rng_seed: int = 0,
    ) -> None:
        self._seeds = seeds
        self._mutators = mutators
        self._lineage = lineage
        self._client = anthropic_client
        self._rng = random.Random(rng_seed)

    def generate(self, job: AttackJob) -> MutatedAttack:
        """Sample a seed for (job.category, job.strategy); apply mutator chain;
        optionally paraphrase; return a MutatedAttack with full lineage.
        """
        seed = self._pick_seed(job)
        directives: list[str] = list(seed.get("mutator_directives") or [])
        seed_int = self._rng.randint(0, 2**31 - 1)
        # Map plan-level directive names to concrete mutator IDs — we only
        # apply concrete mutators that are registered in the stack. Unknown
        # directive strings are passed through; the stack silently skips
        # unregistered ids (see MutatorStack.compose).
        mutator_ids = self._resolve_directives(directives, seed)

        rendered_prompt: str | None = None
        rendered_turns: list[dict[str, Any]] | None = None
        rendered_document: bytes | None = None

        if job.strategy == "crescendo" or seed.get("turns"):
            rendered_turns = [
                {"role": t.get("role", "user"), "content": t.get("content", "")}
                for t in (seed.get("turns") or [])
            ]
            applied_ids: list[str] = []
        else:
            base_prompt = str(seed.get("prompt", ""))
            rendered_prompt, applied_ids = self._mutators.compose(seed, mutator_ids, seed_int)
            if not rendered_prompt:
                rendered_prompt = base_prompt

        refusal_observed = False
        refusal_reframing: str | None = None
        rationale = "deterministic-mutator-only"

        # Single-turn paraphrase pass via Anthropic (skipped for crescendo).
        if self._client is not None and rendered_prompt is not None and rendered_turns is None:
            try:
                paraphrased, refusal_info = self._client.paraphrase(seed, rendered_prompt)
                if refusal_info is not None:
                    refusal_observed = True
                    refusal_reframing = refusal_info.suggested_reframing
                    rationale = f"paraphrase refused; marker={refusal_info.marker_matched!r}"
                else:
                    rendered_prompt = paraphrased
                    rationale = "anthropic-paraphrase"
            except Exception as exc:
                logger.warning("Paraphrase failed; falling back to deterministic: {}", exc)

        attack = MutatedAttack(
            attack_id=str(uuid.uuid4()),
            parent_attack_id=(
                str(job.parent_attack_id) if job.parent_attack_id is not None else None
            ),
            seed_id=str(seed.get("id", job.seed_id or "")),
            category=str(seed.get("category", job.category)),
            strategy=job.strategy,
            mutator_chain=applied_ids,
            rendered_prompt=rendered_prompt,
            rendered_turns=rendered_turns,
            rendered_document=rendered_document,
            rationale=rationale,
            refusal_observed=refusal_observed,
            refusal_reframing_suggestion=refusal_reframing,
            seed_used=dict(seed),
        )
        self._lineage.record(attack)
        return attack

    def escalate(
        self,
        parent: MutatedAttack,
        parent_response: AdapterResponse,
        near_miss: dict[str, Any],
    ) -> MutatedAttack:
        """Tree-of-attacks refinement. Uses the near-miss signal to pick new
        mutator directives. Falls back to deterministic mutation when no LLM
        client is configured.
        """
        _ = parent_response  # consumed via near_miss summary
        seed = dict(parent.seed_used) if parent.seed_used else {}
        # Pull suggested directives from the near-miss; otherwise re-roll the
        # parent's chain on a fresh seed_int.
        directives = list(near_miss.get("suggested_mutation_directives") or [])
        if not directives:
            directives = parent.mutator_chain or list(seed.get("mutator_directives") or [])
        seed_int = self._rng.randint(0, 2**31 - 1)
        mutator_ids = self._resolve_directives(directives, seed)

        base_prompt = parent.rendered_prompt or str(seed.get("prompt", ""))
        rendered_prompt, applied_ids = self._mutators.compose(seed, mutator_ids, seed_int)
        if not rendered_prompt:
            rendered_prompt = base_prompt

        refusal_observed = False
        refusal_reframing: str | None = None
        rationale = "deterministic-mutator-only (escalation)"

        if self._client is not None and rendered_prompt is not None:
            try:
                paraphrased, refusal_info = self._client.paraphrase(seed, rendered_prompt)
                if refusal_info is not None:
                    refusal_observed = True
                    refusal_reframing = refusal_info.suggested_reframing
                    rationale = (
                        f"escalation-paraphrase refused; " f"marker={refusal_info.marker_matched!r}"
                    )
                else:
                    rendered_prompt = paraphrased
                    rationale = "anthropic-paraphrase (escalation)"
            except Exception as exc:
                logger.warning("Escalation paraphrase failed: {}", exc)

        attack = MutatedAttack(
            attack_id=str(uuid.uuid4()),
            parent_attack_id=parent.attack_id,
            seed_id=parent.seed_id,
            category=parent.category,
            strategy=parent.strategy,
            mutator_chain=applied_ids,
            rendered_prompt=rendered_prompt,
            rendered_turns=None,
            rendered_document=None,
            rationale=rationale,
            refusal_observed=refusal_observed,
            refusal_reframing_suggestion=refusal_reframing,
            seed_used=seed,
        )
        # Also detect refusal-like content in the parent response so the
        # caller's escalation loop can react.
        if not refusal_observed and parent_response is not None:
            info = detect_refusal(parent_response.body_text)
            if info is not None:
                attack = attack.model_copy(
                    update={
                        "refusal_observed": True,
                        "refusal_reframing_suggestion": info.suggested_reframing,
                    }
                )
        self._lineage.record(attack)
        return attack

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _pick_seed(self, job: AttackJob) -> dict[str, Any]:
        if job.seed_id is not None:
            return self._seeds.by_id(job.seed_id)
        candidates = self._seeds.by_category(job.category)
        if not candidates:
            raise ValueError(f"No seeds in catalog for category={job.category!r}")
        return self._rng.choice(candidates)

    def _resolve_directives(self, directives: list[str], seed: dict[str, Any]) -> list[str]:
        """Map plan-level directive names like 'wrap_role_play_doctor' to the
        registered mutator ids. Unknown directives are passed through; the
        stack silently skips unregistered ids.
        """
        _ = seed
        mapping = {
            # role-wrap directives
            "wrap_role_play_doctor": "role_wrap.doctor",
            "role_wrap_doctor": "role_wrap.doctor",
            "wrap_role_play_admin": "role_wrap.admin",
            "role_wrap_admin": "role_wrap.admin",
            "wrap_role_play_auditor": "role_wrap.auditor",
            "role_wrap_auditor": "role_wrap.auditor",
            # encoders
            "encode_base64_partial_first_sentence": "encoders.base64",
            "encode_base64": "encoders.base64",
            "leetspeak": "encoders.leetspeak",
            "zero_width": "encoders.zero_width",
            # persuasion
            "frame_as_urgency": "persuasion.urgency",
            "frame_as_authority": "persuasion.authority",
            "frame_as_trust": "persuasion.trust",
        }
        return [mapping.get(d, d) for d in directives]
