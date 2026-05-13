"""Orchestrator Agent — master plan §8.1.

Strategic loop. Picks the next attack from coverage gaps + budget signal +
recent target fingerprint change. Halts when cost accumulates without
producing signal.

Design notes:
  * The orchestrator does NOT import from ``agentforge.redteam.anthropic_client``
    (that is the Red Team's private surface). It receives a ``RedTeamAgent``
    instance via the constructor; the agent owns its own client.
  * The five priority-formula coefficients are class-level constants so a
    Phase-6 AgDR can tune them without code surgery.
  * ``step()`` calls to ``target_adapter.execute`` are wrapped in a try/except
    that translates network/timeout errors to a synthetic
    ``AdapterResponse(error=...)`` rather than aborting the whole run.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol

from loguru import logger
from pydantic import BaseModel, Field

from agentforge.documentation.agent import DocumentationAgent
from agentforge.judge.external_final import ExternalFinalJudge, ExternalVerdict
from agentforge.judge.internal_progress import InternalProgressJudge, InternalVerdict
from agentforge.memory.schemas import AdapterResponse, AttackJob, MutatedAttack
from agentforge.orchestrator.budget_guard import BudgetGuard, HaltReason
from agentforge.orchestrator.coverage import (
    CATEGORIES,
    STRATEGIES,
    CoverageCell,
    CoverageMatrix,
)
from agentforge.orchestrator.prompts import (
    ORCHESTRATOR_SYSTEM_PROMPT,
    ORCHESTRATOR_USER_PROMPT_TEMPLATE,
)
from agentforge.redteam.agent import RedTeamAgent


# ---------------------------------------------------------------------- types


class CategoryStrategy(BaseModel):
    """One planner selection."""

    category: str
    strategy: str
    rationale: str = ""


class PlannerResponse(BaseModel):
    """The Sonnet planner's JSON output."""

    selections: list[CategoryStrategy] = Field(default_factory=list)
    halt_reasons: list[str] = Field(default_factory=list)


class OrchestratorAnthropicClient(Protocol):
    """Anthropic SDK wrapper used by the orchestrator's strategic planner.

    Distinct from the Red Team / Judge / Documentation client protocols so
    each can be substituted independently in tests.
    """

    def plan_batch(self, system: str, user: str) -> PlannerResponse: ...


class TargetExecutor(Protocol):
    """Synchronous adapter surface used by the orchestrator.

    Implementations may wrap the async :class:`agentforge.target_adapter.base.
    TargetAdapter` — the orchestrator only needs a sync ``execute`` that
    returns a :class:`agentforge.memory.schemas.AdapterResponse`.
    """

    def execute(self, attack: MutatedAttack) -> AdapterResponse: ...


class OrchestratorStepResult(BaseModel):
    """One outer-loop iteration's bookkeeping."""

    attacks_executed: int = 0
    findings_written: int = 0
    halted: bool = False
    halt_reason: HaltReason | None = None


# ---------------------------------------------------------------------- agent


class OrchestratorAgent:
    """Master plan §8.1.

    Strategic loop: plan → generate → execute → internal judge → external
    judge → (maybe) document → coverage update → budget tick.
    """

    # Priority-formula coefficients — see §14 Phase 6 (AgDR-tunable).
    OPEN_HIGH_SEV_WEIGHT: float = 2.0
    CATEGORY_UNCOVERED_WEIGHT: float = 1.5
    RECENT_FP_CHANGE_WEIGHT: float = 1.0
    RECENT_PASS_RATE_WEIGHT: float = 1.0
    COST_WITHOUT_SIGNAL_PENALTY: float = 0.5

    # Fallback unit-cost charged per attack when the adapter does not report
    # cost_usd. Keeps the BudgetGuard moving forward during tests / smoke runs.
    DEFAULT_PER_ATTACK_COST_USD: Decimal = Decimal("0.001")

    def __init__(
        self,
        redteam: RedTeamAgent,
        target_adapter: TargetExecutor,
        internal_judge: InternalProgressJudge,
        external_judge: ExternalFinalJudge,
        documentation: DocumentationAgent,
        coverage: CoverageMatrix,
        budget_guard: BudgetGuard,
        anthropic_client: OrchestratorAnthropicClient | None = None,
        *,
        run_id: str,
        target_fingerprint: str = "",
        recent_fingerprint_change_at: datetime | None = None,
        open_findings: Iterable[dict[str, Any]] | None = None,
    ) -> None:
        self._redteam = redteam
        self._target_adapter = target_adapter
        self._internal_judge = internal_judge
        self._external_judge = external_judge
        self._doc = documentation
        self._coverage = coverage
        self._budget = budget_guard
        self._client = anthropic_client
        self._run_id = run_id
        self._target_fingerprint = target_fingerprint
        self._recent_fingerprint_change_at = recent_fingerprint_change_at
        self._open_findings: list[dict[str, Any]] = list(open_findings or [])

    # ------------------------------------------------------------------ plan

    def plan_next_batch(self, batch_size: int = 10) -> list[CategoryStrategy]:
        """Snapshot coverage + verdicts + cost → call Sonnet planner if injected
        → return ranked category-strategy pairs. If no LLM client is injected,
        a deterministic heuristic is used (see :meth:`_deterministic_priority`).
        """
        batch_size = max(1, min(batch_size, 10))  # spec: max 10 per call

        cells = self._coverage.snapshot()
        coverage_payload = [
            {
                "category": c.category,
                "strategy": c.strategy,
                "attempts": c.attempts,
                "passes": c.passes,
                "failures": c.failures,
                "last_attempt_at": (
                    c.last_attempt_at.isoformat() if c.last_attempt_at else None
                ),
                "last_pass_rate": c.last_pass_rate,
            }
            for c in cells
        ]
        budget_state = self._budget.state()
        budget_payload = {
            "spend_usd": str(budget_state.spend_usd),
            "run_type": budget_state.run_type,
            "halted": budget_state.halted,
            "halt_reason": (
                budget_state.halt_reason.value if budget_state.halt_reason else None
            ),
            "attempts_since_last_finding": budget_state.attempts_since_last_finding,
            "spend_since_last_finding_usd": str(
                budget_state.spend_since_last_finding_usd
            ),
        }

        if self._client is not None:
            user = ORCHESTRATOR_USER_PROMPT_TEMPLATE.format(
                coverage_snapshot_json=json.dumps(coverage_payload, sort_keys=True),
                open_findings_summary=json.dumps(self._open_findings, sort_keys=True),
                target_fingerprint=self._target_fingerprint or "(none)",
                recent_fingerprint_change_at=(
                    self._recent_fingerprint_change_at.isoformat()
                    if self._recent_fingerprint_change_at
                    else "null"
                ),
                budget_state_json=json.dumps(budget_payload, sort_keys=True),
                batch_size=batch_size,
            )
            try:
                resp = self._client.plan_batch(ORCHESTRATOR_SYSTEM_PROMPT, user)
                # Honor batch_size — even if Sonnet returns more, cap it.
                return list(resp.selections)[:batch_size]
            except Exception as exc:  # noqa: BLE001 — defensive: fall back
                logger.warning(
                    "Orchestrator planner client failed, falling back to "
                    "deterministic heuristic: {}",
                    exc,
                )

        return self._deterministic_plan(cells, batch_size)

    # ------------------------------------------------------------------ step

    def step(self, batch_size: int = 10) -> OrchestratorStepResult:
        """One outer-loop iteration. Plans a batch, executes each job, and
        stops the moment ``budget_guard.may_continue`` returns False.
        """
        result = OrchestratorStepResult()
        if not self._budget.may_continue():
            result.halted = True
            result.halt_reason = self._budget.halt_reason()
            return result

        selections = self.plan_next_batch(batch_size=batch_size)

        for selection in selections:
            if not self._budget.may_continue():
                break

            job = AttackJob(
                id=uuid.uuid4(),
                run_id=uuid.UUID(self._run_id)
                if _is_uuid(self._run_id)
                else uuid.uuid4(),
                category=selection.category,
                strategy=selection.strategy,
            )

            try:
                attack = self._redteam.generate(job)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Red Team generate failed: {}", exc)
                self._coverage.update(
                    selection.category, selection.strategy, outcome_passed=True
                )
                self._budget.tick_cost(self.DEFAULT_PER_ATTACK_COST_USD)
                continue

            response = self._safe_execute(attack)
            self._budget.tick_target_error(was_error=bool(response.error))

            internal_verdict = self._safe_internal_judge(attack, response)
            _ = internal_verdict  # consumed by Red Team escalation path; orch keeps for log

            expected_safe_behavior = (
                str(attack.seed_used.get("expected_safe_behavior", ""))
                if isinstance(attack.seed_used, dict)
                else ""
            )
            external_verdict = self._safe_external_judge(
                attack, response, expected_safe_behavior
            )

            outcome_passed = self._verdict_passed(external_verdict)
            self._coverage.update(
                attack.category, attack.strategy, outcome_passed=outcome_passed
            )

            if not outcome_passed:
                try:
                    self._doc.write_report(
                        attack=attack,
                        request={
                            "endpoint": (
                                str(attack.seed_used.get("target_endpoint", "unknown"))
                                if isinstance(attack.seed_used, dict)
                                else "unknown"
                            ),
                            "trace_id": str(attack.attack_id),
                        },
                        response=response,
                        verdict=external_verdict,
                        seed=attack.seed_used or {},
                        target_fingerprint=self._target_fingerprint,
                        run_id=self._run_id,
                    )
                    result.findings_written += 1
                    self._budget.tick_finding()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Documentation agent failed: {}", exc)

            # Charge cost — prefer the adapter's reported cost when present,
            # else the conservative default.
            cost = (
                Decimal(str(response.cost_usd))
                if response.cost_usd and response.cost_usd > 0
                else self.DEFAULT_PER_ATTACK_COST_USD
            )
            self._budget.tick_cost(cost)
            # Per-attack timeout check.
            if response.latency_ms:
                self._budget.tick_per_attack_latency(response.latency_ms / 1000.0)
            result.attacks_executed += 1

        result.halted = not self._budget.may_continue()
        result.halt_reason = self._budget.halt_reason()
        return result

    # ----------------------------------------------------------------- utils

    def _safe_execute(self, attack: MutatedAttack) -> AdapterResponse:
        """Wrap the target adapter call so a network/timeout error becomes a
        synthetic :class:`AdapterResponse` rather than aborting the whole run.
        """
        try:
            response = self._target_adapter.execute(attack)
        except Exception as exc:  # noqa: BLE001 — defensive: any exec error
            logger.warning("Target adapter raised: {}", exc)
            return AdapterResponse(
                attack_id=_attack_uuid(attack),
                status_code=0,
                body_text="",
                error=f"target_adapter_exception: {exc}",
            )
        # Coerce: some adapters may return the target_adapter.base.AdapterResponse
        # shape (no attack_id). Translate to memory.schemas.AdapterResponse.
        if isinstance(response, AdapterResponse):
            return response
        return AdapterResponse(
            attack_id=_attack_uuid(attack),
            status_code=getattr(response, "status_code", 0),
            body_text=getattr(response, "body_text", "") or "",
            body_json=getattr(response, "body_json", None),
            latency_ms=getattr(response, "latency_ms", 0.0),
            cost_usd=getattr(response, "cost_usd", 0.0),
            error=getattr(response, "error", None),
        )

    def _safe_internal_judge(
        self, attack: MutatedAttack, response: AdapterResponse
    ) -> InternalVerdict | None:
        try:
            return self._internal_judge.score(attack, response)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Internal judge failed: {}", exc)
            return None

    def _safe_external_judge(
        self,
        attack: MutatedAttack,
        response: AdapterResponse,
        expected_safe_behavior: str,
    ) -> ExternalVerdict | None:
        try:
            return self._external_judge.score(
                attack, response, expected_safe_behavior
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("External judge failed: {}", exc)
            return None

    @staticmethod
    def _verdict_passed(verdict: ExternalVerdict | None) -> bool:
        """A cell passes iff no rubric failed in the binding verdict.

        A None verdict (judge crash) is treated as a pass so the cell is not
        blamed for a platform bug. The orchestrator logs the underlying error.
        """
        if verdict is None:
            return True
        for outcome in verdict.outcomes.values():
            if not outcome.passed and not outcome.abstained:
                return False
        return True

    # -------------------------------------------------- deterministic planner

    def _deterministic_plan(
        self, cells: list[CoverageCell], batch_size: int
    ) -> list[CategoryStrategy]:
        """Phase-4 fallback used when no Sonnet client is wired.

        priority = (open_high_severity_count * OPEN_HIGH_SEV_WEIGHT)
                 + (category_uncovered * CATEGORY_UNCOVERED_WEIGHT)
                 + (recent_target_fingerprint_change * RECENT_FP_CHANGE_WEIGHT)
                 - (recent_pass_rate * RECENT_PASS_RATE_WEIGHT)
                 - (cost_without_signal_penalty * COST_WITHOUT_SIGNAL_PENALTY)
        """
        # Tally open high-sev counts per category.
        open_hi_by_cat: dict[str, int] = {}
        for f in self._open_findings:
            sev = str(f.get("severity", "")).lower()
            cat = str(f.get("category", ""))
            if sev in ("high", "critical") and cat:
                open_hi_by_cat[cat] = open_hi_by_cat.get(cat, 0) + 1

        # Recent target change → boost everything until the new fingerprint
        # has been swept. Only counts if there IS a recorded change time.
        recent_fp_change = 1.0 if self._recent_fingerprint_change_at else 0.0

        budget_state = self._budget.state()
        cost_without_signal_signal = (
            1.0 if budget_state.attempts_since_last_finding > 0 else 0.0
        )

        scored: list[tuple[float, CategoryStrategy]] = []
        for c in cells:
            uncovered = 1.0 if c.attempts == 0 else 0.0
            recent_pass_rate = c.last_pass_rate if c.last_pass_rate is not None else 0.0
            open_hi = open_hi_by_cat.get(c.category, 0)
            priority = (
                open_hi * self.OPEN_HIGH_SEV_WEIGHT
                + uncovered * self.CATEGORY_UNCOVERED_WEIGHT
                + recent_fp_change * self.RECENT_FP_CHANGE_WEIGHT
                - recent_pass_rate * self.RECENT_PASS_RATE_WEIGHT
                - cost_without_signal_signal * self.COST_WITHOUT_SIGNAL_PENALTY
            )
            scored.append(
                (
                    priority,
                    CategoryStrategy(
                        category=c.category,
                        strategy=c.strategy,
                        rationale=(
                            f"deterministic: priority={priority:.2f}, "
                            f"uncovered={int(uncovered)}, open_hi={open_hi}"
                        ),
                    ),
                )
            )
        # Stable sort: higher priority first, then (category, strategy) for ties.
        scored.sort(
            key=lambda kv: (-kv[0], kv[1].category, kv[1].strategy)
        )
        # Restrict to the canonical category × strategy product so the
        # deterministic plan never proposes a typo cell.
        valid = {(cat, strat) for cat in CATEGORIES for strat in STRATEGIES}
        out: list[CategoryStrategy] = []
        for _priority, sel in scored:
            if (sel.category, sel.strategy) in valid:
                out.append(sel)
                if len(out) >= batch_size:
                    break
        return out


# ------------------------------------------------------------------ helpers


def _is_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _attack_uuid(attack: MutatedAttack) -> uuid.UUID:
    """Translate the attack's string id to a UUID for schemas.AdapterResponse."""
    try:
        return uuid.UUID(attack.attack_id)
    except (ValueError, AttributeError, TypeError):
        return uuid.uuid4()


__all__ = [
    "CategoryStrategy",
    "OrchestratorAgent",
    "OrchestratorAnthropicClient",
    "OrchestratorStepResult",
    "PlannerResponse",
    "TargetExecutor",
]
