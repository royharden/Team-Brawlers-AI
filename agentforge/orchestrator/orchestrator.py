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
  * **Persistence (AgDR-0017):** when a ``session_factory`` is injected, the
    orchestrator writes ``Run`` / ``AttackJob`` / ``AttackTrace`` / ``Verdict``
    / ``CostLedgerEntry`` rows as side-effects of ``step()``. Without a
    session_factory the orchestrator runs in memory-only mode (preserves
    test compatibility).
"""

from __future__ import annotations

import contextlib
import json
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agentforge.documentation.agent import DocumentationAgent
from agentforge.judge.external_final import ExternalFinalJudge, ExternalVerdict
from agentforge.judge.internal_progress import InternalProgressJudge, InternalVerdict
from agentforge.memory.models import (
    AttackJob as AttackJobRow,
)
from agentforge.memory.models import (
    AttackTrace as AttackTraceRow,
)
from agentforge.memory.models import (
    CostLedgerEntry as CostLedgerEntryRow,
)
from agentforge.memory.models import (
    Run as RunRow,
)
from agentforge.memory.models import (
    Verdict as VerdictRow,
)
from agentforge.memory.schemas import AdapterResponse, AttackJob, MutatedAttack
from agentforge.orchestrator.budget_guard import BudgetGuard, HaltReason
from agentforge.orchestrator.coverage import (
    CATEGORIES,
    STRATEGIES,
    CoverageCell,
    CoverageMatrix,
)
from agentforge.orchestrator.defense_delta import DefenseDelta
from agentforge.orchestrator.prompts import (
    ORCHESTRATOR_SYSTEM_PROMPT,
    ORCHESTRATOR_USER_PROMPT_TEMPLATE,
)
from agentforge.pricing import PricingTable
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

    # Per-call cost estimates used for cost_ledger entries when the wrappers
    # themselves do not surface token counts (AgDR-0016 follow-on #3). Real
    # cost can drift from these; the BudgetGuard remains the binding ceiling.
    _COST_ESTIMATE_INTERNAL_JUDGE_USD: Decimal = Decimal("0.002400")
    _COST_ESTIMATE_EXTERNAL_JUDGE_USD: Decimal = Decimal("0.024000")
    _COST_ESTIMATE_DOC_AGENT_USD: Decimal = Decimal("0.036000")
    _COST_ESTIMATE_REDTEAM_USD: Decimal = Decimal("0.000000")  # OpenRouter :free
    _DEFAULT_INTERNAL_JUDGE_MODEL: str = "claude-haiku-4-6"
    _DEFAULT_EXTERNAL_JUDGE_MODEL: str = "claude-sonnet-4-6"
    _DEFAULT_DOC_AGENT_MODEL: str = "claude-sonnet-4-6"
    _DEFAULT_REDTEAM_MODEL: str = "nvidia/nemotron-3-super-120b-a12b:free"

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
        session_factory: Callable[[], Session] | None = None,
        run_type: str = "exploratory",
        pricing: PricingTable | None = None,
        usage_sources: dict[str, Any] | None = None,
        target_fingerprinter: Callable[[], str] | None = None,
        defense_delta: DefenseDelta | None = None,
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
        # AgDR-0017: persistence layer. None = memory-only (default; preserves
        # test compat). Non-None = each step() side-effects Run / AttackJob /
        # AttackTrace / Verdict / CostLedgerEntry rows.
        self._session_factory = session_factory
        self._run_type = run_type
        self._run_persisted = False
        # Sub-plan Next03 §4.3 (AgDR-0021): when both pricing and usage_sources
        # are injected, the cost_ledger persister reads real per-call token
        # counts from each wrapper's `last_usage` and computes cost from
        # pricing.yml. Falls back to the class-level _COST_ESTIMATE_*
        # constants when either is missing or last_usage is None.
        # usage_sources keyed by agent_role: "internal_judge", "external_judge",
        # "documentation", "orchestrator_planner".
        self._pricing = pricing
        self._usage_sources: dict[str, Any] = dict(usage_sources or {})
        # Sub-plan Next03 §4.4 (AgDR-0018): Defense Delta auto-snapshot. When
        # both are wired, step() reads the fingerprinter at top-of-loop and
        # writes a snapshot row each time it CHANGES. None = AgDR-0017
        # behavior (the seeder + manual `tb attack` runs are responsible for
        # snapshots).
        self._target_fingerprinter = target_fingerprinter
        self._defense_delta = defense_delta
        self._last_seen_fingerprint: str | None = target_fingerprint or None

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
                "last_attempt_at": (c.last_attempt_at.isoformat() if c.last_attempt_at else None),
                "last_pass_rate": c.last_pass_rate,
            }
            for c in cells
        ]
        budget_state = self._budget.state()
        budget_payload = {
            "spend_usd": str(budget_state.spend_usd),
            "run_type": budget_state.run_type,
            "halted": budget_state.halted,
            "halt_reason": (budget_state.halt_reason.value if budget_state.halt_reason else None),
            "attempts_since_last_finding": budget_state.attempts_since_last_finding,
            "spend_since_last_finding_usd": str(budget_state.spend_since_last_finding_usd),
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
            except Exception as exc:
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

        When a ``session_factory`` was injected at construction, every phase
        in this loop also writes to the platform DB so the dashboard reflects
        live state (Run / AttackJob / AttackTrace / Verdict / CostLedgerEntry).
        Persistence failures are logged at WARNING but never abort the loop.
        """
        # Ensure the run row exists before doing anything else this step.
        self._persist_run_if_needed()

        # Sub-plan Next03 §4.4 (AgDR-0018): refresh the target fingerprint at
        # top-of-loop and snapshot Defense Delta if it changed. No-op when the
        # fingerprinter or defense_delta isn't wired (memory-only / test mode).
        self._refresh_fingerprint_and_maybe_snapshot()

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
                run_id=uuid.UUID(self._run_id) if _is_uuid(self._run_id) else uuid.uuid4(),
                category=selection.category,
                strategy=selection.strategy,
            )
            # Persist the job row before Red Team runs -- this way an exception
            # there still leaves an audit trail.
            self._persist_attack_job(job, status="running")

            try:
                attack = self._redteam.generate(job)
            except Exception as exc:
                logger.warning("Red Team generate failed: {}", exc)
                self._coverage.update(selection.category, selection.strategy, outcome_passed=True)
                self._budget.tick_cost(self.DEFAULT_PER_ATTACK_COST_USD)
                self._persist_attack_job(job, status="redteam_error", upsert=True)
                self._persist_cost_ledger(
                    agent_role="redteam",
                    provider="openrouter",
                    model=self._DEFAULT_REDTEAM_MODEL,
                    cost_usd=self.DEFAULT_PER_ATTACK_COST_USD,
                )
                continue

            response = self._safe_execute(attack)
            self._budget.tick_target_error(was_error=bool(response.error))

            # Persist the trace AFTER the adapter call so we capture the real
            # latency + status + body shape.
            trace_id = self._persist_attack_trace(job=job, attack=attack, response=response)

            internal_verdict = self._safe_internal_judge(attack, response)
            self._persist_verdict(
                attack_trace_id=trace_id,
                layer="internal_progress",
                verdict=internal_verdict,
                model=self._DEFAULT_INTERNAL_JUDGE_MODEL,
            )

            expected_safe_behavior = (
                str(attack.seed_used.get("expected_safe_behavior", ""))
                if isinstance(attack.seed_used, dict)
                else ""
            )
            external_verdict = self._safe_external_judge(attack, response, expected_safe_behavior)
            self._persist_verdict(
                attack_trace_id=trace_id,
                layer="external_final",
                verdict=external_verdict,
                model=(
                    external_verdict.model
                    if external_verdict is not None and external_verdict.model
                    else self._DEFAULT_EXTERNAL_JUDGE_MODEL
                ),
            )

            outcome_passed = self._verdict_passed(external_verdict)
            self._coverage.update(attack.category, attack.strategy, outcome_passed=outcome_passed)

            doc_agent_ran = False
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
                    doc_agent_ran = True
                except Exception as exc:
                    logger.warning("Documentation agent failed: {}", exc)

            # Per-attack cost: prefer the adapter's reported cost; else the
            # conservative default. Used by BudgetGuard for halt arithmetic.
            adapter_cost = (
                Decimal(str(response.cost_usd))
                if response.cost_usd and response.cost_usd > 0
                else self.DEFAULT_PER_ATTACK_COST_USD
            )
            self._budget.tick_cost(adapter_cost)

            # Per-role cost_ledger rows (best-effort estimates for now; real
            # token counts would come from the wrappers per AgDR-0016 #3).
            self._persist_cost_ledger(
                agent_role="redteam",
                provider="openrouter",
                model=self._DEFAULT_REDTEAM_MODEL,
                cost_usd=self._COST_ESTIMATE_REDTEAM_USD,
            )
            self._persist_cost_ledger(
                agent_role="adapter",
                provider="sidecar",
                model=str(getattr(self._target_adapter, "name", "sidecar_direct")),
                cost_usd=adapter_cost,
            )
            if internal_verdict is not None:
                self._persist_cost_ledger(
                    agent_role="internal_judge",
                    provider="anthropic",
                    model=self._DEFAULT_INTERNAL_JUDGE_MODEL,
                    cost_usd=self._COST_ESTIMATE_INTERNAL_JUDGE_USD,
                )
            if external_verdict is not None:
                self._persist_cost_ledger(
                    agent_role="external_judge",
                    provider="anthropic",
                    model=(external_verdict.model or self._DEFAULT_EXTERNAL_JUDGE_MODEL),
                    cost_usd=self._COST_ESTIMATE_EXTERNAL_JUDGE_USD,
                )
            if doc_agent_ran:
                self._persist_cost_ledger(
                    agent_role="documentation",
                    provider="anthropic",
                    model=self._DEFAULT_DOC_AGENT_MODEL,
                    cost_usd=self._COST_ESTIMATE_DOC_AGENT_USD,
                )

            # Per-attack timeout check.
            if response.latency_ms:
                self._budget.tick_per_attack_latency(response.latency_ms / 1000.0)
            self._persist_attack_job(job, status="completed", upsert=True)
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
        except Exception as exc:
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
        except Exception as exc:
            logger.warning("Internal judge failed: {}", exc)
            return None

    def _safe_external_judge(
        self,
        attack: MutatedAttack,
        response: AdapterResponse,
        expected_safe_behavior: str,
    ) -> ExternalVerdict | None:
        try:
            return self._external_judge.score(attack, response, expected_safe_behavior)
        except Exception as exc:
            logger.warning("External judge failed: {}", exc)
            return None

    # --------------------------------------------------- persistence (AgDR-0017)

    def _refresh_fingerprint_and_maybe_snapshot(self) -> None:
        """Sub-plan Next03 §4.4: call the injected fingerprinter, detect a
        change, and persist a DefenseDelta snapshot row when one occurs.

        - No fingerprinter wired → no-op (preserves AgDR-0017 behavior).
        - Fingerprinter returns falsy → leave state unchanged.
        - First non-None observation just records the baseline; only later
          *changes* trigger a snapshot. The seeder owns the initial row.
        """
        if self._target_fingerprinter is None or self._defense_delta is None:
            return
        try:
            new_fp = self._target_fingerprinter()
        except Exception as exc:  # broad: network / curl / fingerprint helper
            logger.warning("target_fingerprinter raised: {}", exc)
            return
        if not new_fp:
            return
        self._target_fingerprint = new_fp
        if self._last_seen_fingerprint is None:
            self._last_seen_fingerprint = new_fp
            return
        if new_fp == self._last_seen_fingerprint:
            return
        # Fingerprint changed — snapshot.
        try:
            self._defense_delta.snapshot(new_fp)
        except Exception as exc:
            logger.warning("DefenseDelta.snapshot failed for {}: {}", new_fp, exc)
        self._recent_fingerprint_change_at = datetime.now(UTC)
        self._last_seen_fingerprint = new_fp

    def _persist_run_if_needed(self) -> None:
        """Insert the ``runs`` row on the first persistence operation.

        Idempotent: if a row with this run_id already exists (e.g. the CLI
        seeded it), we leave it alone. If ``session_factory`` was never
        provided we're in memory-only mode -- no-op.
        """
        if self._run_persisted or self._session_factory is None:
            return
        session = self._session_factory()
        try:
            existing = session.query(RunRow).filter(RunRow.id == self._run_id).one_or_none()
            if existing is None:
                row = RunRow(
                    id=self._run_id,
                    started_at=datetime.now(UTC),
                    run_type=self._run_type,
                    status="running",
                    model_resolution_json="{}",
                    total_cost_usd=Decimal("0"),
                )
                session.add(row)
                session.commit()
            self._run_persisted = True
        except Exception as exc:
            session.rollback()
            logger.warning("Failed to persist Run row: {}", exc)
        finally:
            session.close()

    def _persist_attack_job(
        self, job: AttackJob, *, status: str = "running", upsert: bool = False
    ) -> None:
        """Insert (or upsert) an ``attack_jobs`` row.

        ``upsert=True`` updates the status column of an existing row; this is
        how we record the post-step "completed" or "redteam_error" status
        without losing the original insertion timestamp.
        """
        if self._session_factory is None:
            return
        session = self._session_factory()
        try:
            row_id = str(job.id)
            existing = session.query(AttackJobRow).filter(AttackJobRow.id == row_id).one_or_none()
            if existing is not None:
                if upsert:
                    existing.status = status
                    session.commit()
                return
            row = AttackJobRow(
                id=row_id,
                run_id=self._run_id,
                category=job.category,
                strategy=job.strategy,
                seed_id=getattr(job, "seed_id", None),
                status=status,
            )
            session.add(row)
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.warning("Failed to persist AttackJob: {}", exc)
        finally:
            session.close()

    def _persist_attack_trace(
        self, *, job: AttackJob, attack: MutatedAttack, response: AdapterResponse
    ) -> str:
        """Insert one ``attack_traces`` row and return its id.

        The returned id is the FK target for the two ``verdicts`` rows we
        write next. Returns a synthetic in-memory id when persistence is
        disabled -- the verdicts persistence then no-ops too.
        """
        trace_id = str(uuid.uuid4())
        if self._session_factory is None:
            return trace_id
        session = self._session_factory()
        try:
            response_dict: dict[str, Any] = {
                "status_code": int(getattr(response, "status_code", 0) or 0),
                "latency_ms": float(getattr(response, "latency_ms", 0.0) or 0.0),
                "error": getattr(response, "error", None),
            }
            # Truncate body_text aggressively before persistence so attack_traces
            # rows stay small. The Documentation Agent gets the full body.
            body_preview = ""
            with contextlib.suppress(AttributeError, TypeError, ValueError):
                body_preview = (response.body_text or "")[:512]
            response_dict["body_text_preview"] = body_preview

            request_dict = {
                "endpoint": (
                    str(attack.seed_used.get("target_endpoint", "unknown"))
                    if isinstance(attack.seed_used, dict)
                    else "unknown"
                ),
                "trace_id": str(attack.attack_id),
            }

            row = AttackTraceRow(
                id=trace_id,
                attack_job_id=str(job.id),
                mutator_chain_json=json.dumps(list(attack.mutator_chain or [])),
                rendered_prompt=(attack.rendered_prompt or "")[:4096],
                rendered_document=None,
                target_request_json=json.dumps(request_dict),
                target_response_json=json.dumps(response_dict),
                latency_ms=int(response.latency_ms or 0),
                target_error=response.error,
            )
            session.add(row)
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.warning("Failed to persist AttackTrace: {}", exc)
        finally:
            session.close()
        return trace_id

    def _persist_verdict(
        self,
        *,
        attack_trace_id: str,
        layer: str,
        verdict: InternalVerdict | ExternalVerdict | None,
        model: str,
    ) -> None:
        """Insert one ``verdicts`` row. ``layer`` must be one of
        ``internal_progress`` or ``external_final`` (CHECK-constrained by the
        schema).
        """
        if self._session_factory is None or verdict is None:
            return
        # Derive outcome + confidence + rubric_results_json from the verdict.
        outcomes = getattr(verdict, "outcomes", {}) or {}
        passed_count = sum(
            1
            for o in outcomes.values()
            if getattr(o, "passed", False) and not getattr(o, "abstained", False)
        )
        failed_count = sum(
            1
            for o in outcomes.values()
            if not getattr(o, "passed", True) and not getattr(o, "abstained", False)
        )
        if failed_count > 0:
            outcome = "failed"
        elif passed_count > 0:
            outcome = "passed"
        else:
            outcome = "abstain"
        confidences = [float(getattr(o, "confidence", 0.0) or 0.0) for o in outcomes.values()]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        rubric_results = [
            {
                "rubric_id": rid,
                "passed": bool(getattr(o, "passed", False)),
                "abstained": bool(getattr(o, "abstained", False)),
                "confidence": float(getattr(o, "confidence", 0.0) or 0.0),
            }
            for rid, o in outcomes.items()
        ]

        session = self._session_factory()
        try:
            row = VerdictRow(
                id=str(uuid.uuid4()),
                attack_trace_id=attack_trace_id,
                layer=layer,
                rubric_results_json=json.dumps(rubric_results),
                outcome=outcome,
                confidence=avg_confidence,
                model=model,
            )
            session.add(row)
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.warning("Failed to persist Verdict({}): {}", layer, exc)
        finally:
            session.close()

    def _persist_cost_ledger(
        self,
        *,
        agent_role: str,
        provider: str,
        model: str,
        cost_usd: Decimal,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Insert one ``cost_ledger`` row.

        Sub-plan Next03 §4.3 (AgDR-0021): when both ``self._pricing`` and
        ``self._usage_sources[agent_role]`` are wired AND the wrapper's
        ``last_usage`` is set, this replaces the caller-supplied
        ``cost_usd`` / ``input_tokens`` / ``output_tokens`` with real
        per-call values computed from ``config/pricing.yml``. Otherwise
        falls back to the caller-supplied class-level estimates so existing
        tests + memory-only mode behave identically to AgDR-0017.
        """
        if self._session_factory is None:
            return

        # Try to upgrade to real-token pricing (AgDR-0021).
        # Sub-plan Next04 (AgDR-0023): prefer `last_aggregate_usage` when the
        # wrapper exposes it (SonnetJudgeClient sums across the 5–7 rubrics
        # it scores per attack); fall back to per-call `last_usage` for the
        # other three wrappers.
        usage_src = self._usage_sources.get(agent_role)
        if usage_src is not None and self._pricing is not None:
            usage = getattr(usage_src, "last_aggregate_usage", None) or getattr(
                usage_src, "last_usage", None
            )
            if usage is not None:
                with contextlib.suppress(Exception):
                    real_cost = self._pricing.cost_for_call(
                        provider=provider,
                        model=getattr(usage, "model", model),
                        input_tokens=int(getattr(usage, "input_tokens", 0)),
                        output_tokens=int(getattr(usage, "output_tokens", 0)),
                    )
                    cost_usd = real_cost
                    input_tokens = int(getattr(usage, "input_tokens", 0))
                    output_tokens = int(getattr(usage, "output_tokens", 0))
                    model = getattr(usage, "model", model)

        session = self._session_factory()
        try:
            row = CostLedgerEntryRow(
                id=str(uuid.uuid4()),
                run_id=self._run_id,
                agent_role=agent_role,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            )
            session.add(row)
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.warning("Failed to persist CostLedgerEntry({}): {}", agent_role, exc)
        finally:
            session.close()

    def end_run(self, *, status: str = "completed", halt_reason: str | None = None) -> None:
        """Finalize the current ``runs`` row.

        Called by the CLI (or other harness) after the campaign's last
        ``step()``. Updates ``ended_at`` + ``status`` + ``total_cost_usd``
        (summed from cost_ledger) + ``halt_reason``. No-op if persistence
        was never enabled.
        """
        if self._session_factory is None:
            return
        session = self._session_factory()
        try:
            run = session.query(RunRow).filter(RunRow.id == self._run_id).one_or_none()
            if run is None:
                return
            run.ended_at = datetime.now(UTC)
            run.status = status
            if halt_reason is not None:
                run.halt_reason = halt_reason
            # Sum the cost_ledger rows for this run into total_cost_usd.
            total = (
                session.query(CostLedgerEntryRow)
                .filter(CostLedgerEntryRow.run_id == self._run_id)
                .with_entities(CostLedgerEntryRow.cost_usd)
                .all()
            )
            run.total_cost_usd = sum((Decimal(str(r[0])) for r in total), Decimal("0"))
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.warning("Failed to finalize Run row: {}", exc)
        finally:
            session.close()

    # ------------------------------------------------------------ helpers cont.

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
        cost_without_signal_signal = 1.0 if budget_state.attempts_since_last_finding > 0 else 0.0

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
        scored.sort(key=lambda kv: (-kv[0], kv[1].category, kv[1].strategy))
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
