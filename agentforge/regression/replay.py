"""Replay one frozen regression case against the live (or fake) target.

Master plan §13. The PRD's regression-harness clause states verbatim that
"the platform must maintain a regression harness that converts confirmed
exploits into deterministic, repeatable test cases and runs them against
every new version of the target system." :class:`Replay` is the per-case
unit of that promise.

The Red Team agent is intentionally NOT a dependency here. The mutator
chain that built the original exploit was already applied during the run
that discovered the bug; the rendered prompt is frozen inside the
regression JSON, so replay just re-sends it. This keeps regression replay
free of any Red Team SDK + provider keys and free of any chance of
re-mutating the prompt into a *different* attack.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from agentforge.judge.external_final import ExternalFinalJudge
from agentforge.memory.schemas import AdapterResponse, MutatedAttack
from agentforge.regression.case_schema import RegressionCase, ReplayOutcome


class TargetExecutor(Protocol):
    """Sync adapter surface used by regression replay.

    Mirrors the shape the Orchestrator uses for routine attack execution,
    but takes the rendered payload directly (the regression case already
    carries the rendered prompt — there is no Red Team mutation step).
    """

    def execute(
        self,
        *,
        rendered_prompt: str | None,
        rendered_turns: list[dict[str, Any]] | None,
        target_endpoint: str | None,
    ) -> AdapterResponse: ...


class Replay:
    """Replay one regression case against a target executor + judge."""

    def __init__(
        self,
        target_executor: TargetExecutor,
        external_judge: ExternalFinalJudge,
    ) -> None:
        self._target = target_executor
        self._judge = external_judge

    # ------------------------------------------------------------------ run

    def run_case(
        self,
        case: RegressionCase,
        *,
        target_fingerprint: str,
    ) -> ReplayOutcome:
        """Execute one case and score the response.

        Steps:

        1. Build a synthetic :class:`MutatedAttack` from the frozen case so
           the External Final Judge sees the same envelope shape it sees
           in production.
        2. Call ``target_executor.execute(...)``. Any exception becomes an
           ``AdapterResponse(error=...)`` and the observed outcome flips
           to ``"error"`` (no scoring attempted).
        3. Score with the external judge.
        4. Aggregate: any failed rubric → ``observed_outcome="fail"``;
           else ``"passed"``.
        5. ``matched_expected`` is True iff the observed outcome equals
           the case's expected outcome (always ``"fail"``).
        """
        attack = self._synthetic_attack(case)
        timestamp = datetime.now(UTC)

        t0 = time.perf_counter()
        response: AdapterResponse
        error: str | None = None
        try:
            response = self._target.execute(
                rendered_prompt=case.prompt,
                rendered_turns=case.turns,
                target_endpoint=case.target_endpoint,
            )
        except Exception as exc:
            error = f"target_executor_exception: {exc}"
            response = AdapterResponse(
                attack_id=uuid4(),
                status_code=0,
                body_text="",
                error=error,
            )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        # If the adapter itself surfaced an error (either raised OR returned an
        # AdapterResponse with .error set), we don't score — observed=error.
        if error is not None or response.error:
            return ReplayOutcome(
                vr_id=case.vr_id,
                case_id=case.id,
                timestamp=timestamp,
                target_fingerprint=target_fingerprint,
                observed_outcome="error",
                matched_expected=False,
                judge_verdict_summary="",
                judge_outcomes={},
                latency_ms=latency_ms,
                error=error or response.error,
            )

        verdict = self._judge.score(
            attack=attack,
            response=response,
            expected_safe_behavior=case.expected_safe_behavior,
        )

        # Aggregate per-rubric outcomes into a single observed result.
        judge_outcomes: dict[str, str] = {}
        any_failed = False
        for rid, oc in verdict.outcomes.items():
            if oc.abstained:
                judge_outcomes[rid] = "abstained"
            elif oc.passed:
                judge_outcomes[rid] = "passed"
            else:
                judge_outcomes[rid] = "failed"
                any_failed = True

        observed: str = "fail" if any_failed else "passed"
        matched = observed == "fail"  # expected is always "fail"

        return ReplayOutcome(
            vr_id=case.vr_id,
            case_id=case.id,
            timestamp=timestamp,
            target_fingerprint=target_fingerprint,
            observed_outcome=observed,  # type: ignore[arg-type]
            matched_expected=matched,
            judge_verdict_summary=verdict.summary,
            judge_outcomes=judge_outcomes,
            latency_ms=latency_ms,
            error=None,
        )

    # ----------------------------------------------------------------- utils

    @staticmethod
    def _synthetic_attack(case: RegressionCase) -> MutatedAttack:
        """Construct the :class:`MutatedAttack` envelope for the judge.

        Replay never re-mutates — the rendered prompt is taken verbatim
        from the regression case. ``parent_attack_id`` is left None: this
        attack is a synthetic stand-in, not a lineage descendant.
        """
        return MutatedAttack(
            attack_id=f"replay-{case.vr_id}-{uuid4().hex[:8]}",
            parent_attack_id=None,
            seed_id=case.id,
            category=case.category,
            strategy="regression_replay",
            mutator_chain=[],  # frozen prompt — no live mutation
            rendered_prompt=case.prompt,
            rendered_turns=case.turns,
            rationale="regression-replay",
            seed_used={"id": case.id, "category": case.category},
        )


__all__ = ["Replay", "TargetExecutor"]
