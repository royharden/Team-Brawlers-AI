"""OrchestratorAgent tests — master plan §8.1 / Phase 4."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import Session

from agentforge.config import BudgetConfig
from agentforge.judge.external_final import ExternalVerdict
from agentforge.judge.internal_progress import InternalVerdict
from agentforge.judge.rubrics.base import RubricOutcome
from agentforge.memory.schemas import AdapterResponse, AttackJob, MutatedAttack
from agentforge.orchestrator.budget_guard import BudgetGuard, HaltReason
from agentforge.orchestrator.coverage import CoverageMatrix
from agentforge.orchestrator.orchestrator import (
    CategoryStrategy,
    OrchestratorAgent,
    PlannerResponse,
)

# ----------------------------------------------------------------- test fakes


class FakePlanner:
    """OrchestratorAnthropicClient stub returning a pre-baked PlannerResponse."""

    def __init__(self, selections: list[CategoryStrategy]) -> None:
        self.selections = selections
        self.calls = 0

    def plan_batch(self, system: str, user: str) -> PlannerResponse:
        self.calls += 1
        return PlannerResponse(selections=list(self.selections))


class FakeRedTeam:
    def __init__(self) -> None:
        self.calls: list[AttackJob] = []

    def generate(self, job: AttackJob) -> MutatedAttack:
        self.calls.append(job)
        return MutatedAttack(
            attack_id=str(uuid.uuid4()),
            seed_id=job.seed_id or "SEED-X",
            category=job.category,
            strategy=job.strategy,
            rendered_prompt=f"prompt:{job.category}:{job.strategy}",
            seed_used={
                "id": "SEED-X",
                "expected_safe_behavior": "Refuse politely.",
                "target_endpoint": "brief",
            },
        )


class FakeTargetAdapter:
    """Returns a clean schemas.AdapterResponse for every call."""

    def __init__(self, *, raise_for_strategy: str | None = None) -> None:
        self.raise_for_strategy = raise_for_strategy
        self.calls: list[MutatedAttack] = []

    def execute(self, attack: MutatedAttack) -> AdapterResponse:
        self.calls.append(attack)
        if self.raise_for_strategy == attack.strategy:
            raise RuntimeError("simulated network failure")
        return AdapterResponse(
            attack_id=uuid.UUID(attack.attack_id),
            status_code=200,
            body_text="I cannot help with that request.",
            latency_ms=120.0,
            cost_usd=0.0,
        )


class FakeInternalJudge:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any]] = []

    def score(self, attack: Any, response: Any) -> InternalVerdict:
        self.calls.append((attack, response))
        return InternalVerdict(outcomes={}, summary="ok", latency_ms=1.0)


class FakeExternalJudge:
    """Returns an ExternalVerdict whose pass/fail is configurable per call."""

    def __init__(self, *, all_pass: bool = True) -> None:
        self.all_pass = all_pass
        self.calls: list[tuple[Any, Any, str]] = []

    def score(
        self,
        attack: MutatedAttack,
        response: AdapterResponse,
        expected_safe_behavior: str,
    ) -> ExternalVerdict:
        self.calls.append((attack, response, expected_safe_behavior))
        if self.all_pass:
            outcomes = {
                "fake_rubric": RubricOutcome(passed=True, confidence=1.0, rationale="clean")
            }
            return ExternalVerdict(
                outcomes=outcomes,
                summary="passed",
                severity="Info",
                defcon=5,
                safety_score_0_100=100,
                failed_rubrics=[],
            )
        outcomes = {"fake_rubric": RubricOutcome(passed=False, confidence=1.0, rationale="failed")}
        return ExternalVerdict(
            outcomes=outcomes,
            summary="failed",
            severity="High",
            defcon=2,
            safety_score_0_100=30,
            failed_rubrics=["fake_rubric"],
        )


class FakeDocAgent:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def write_report(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"vr_id": f"VR-{len(self.calls):04d}"}


# ------------------------------------------------------------------- helpers


def _cfg_generous() -> BudgetConfig:
    return BudgetConfig(  # type: ignore[call-arg]
        BUDGET_SMOKE_USD=Decimal("100.00"),
        BUDGET_SEEDED_USD=Decimal("100.00"),
        BUDGET_EXPLORATORY_USD=Decimal("100.00"),
        BUDGET_PER_DAY_USD=Decimal("1000.00"),
        BUDGET_HALT_AFTER_N_NULL_RUNS=9999,
        BUDGET_NULL_RUN_SPEND_THRESHOLD_USD=Decimal("1000.00"),
        BUDGET_PER_ATTACK_TIMEOUT_S=60,
        BUDGET_TARGET_ERROR_RATE_HALT=0.99,
    )


def _build(
    session_factory: Callable[[], Session],
    *,
    planner: FakePlanner | None = None,
    redteam: FakeRedTeam | None = None,
    target_adapter: FakeTargetAdapter | None = None,
    internal: FakeInternalJudge | None = None,
    external: FakeExternalJudge | None = None,
    doc: FakeDocAgent | None = None,
    budget_cfg: BudgetConfig | None = None,
) -> tuple[OrchestratorAgent, dict[str, Any]]:
    redteam = redteam or FakeRedTeam()
    target_adapter = target_adapter or FakeTargetAdapter()
    internal = internal or FakeInternalJudge()
    external = external or FakeExternalJudge(all_pass=True)
    doc = doc or FakeDocAgent()
    cfg = budget_cfg or _cfg_generous()
    guard = BudgetGuard(cfg, run_type="exploratory")
    coverage = CoverageMatrix(session_factory)
    orch = OrchestratorAgent(
        redteam=redteam,  # type: ignore[arg-type]
        target_adapter=target_adapter,  # type: ignore[arg-type]
        internal_judge=internal,  # type: ignore[arg-type]
        external_judge=external,  # type: ignore[arg-type]
        documentation=doc,  # type: ignore[arg-type]
        coverage=coverage,
        budget_guard=guard,
        anthropic_client=planner,
        run_id=str(uuid.uuid4()),
    )
    bag = {
        "redteam": redteam,
        "target_adapter": target_adapter,
        "internal": internal,
        "external": external,
        "doc": doc,
        "coverage": coverage,
        "guard": guard,
    }
    return orch, bag


# --------------------------------------------------------------------- tests


@pytest.mark.unit
def test_plan_next_batch_uses_fake_planner_client(
    session_factory: Callable[[], Session],
) -> None:
    """When an `OrchestratorAnthropicClient` is injected, `plan_next_batch` delegates to it and returns its `PlannerResponse.selections`."""
    planner = FakePlanner(
        [
            CategoryStrategy(category="prompt_injection", strategy="single_turn", rationale="a"),
            CategoryStrategy(category="tool_misuse", strategy="role_play", rationale="b"),
        ]
    )
    orch, _ = _build(session_factory, planner=planner)
    selections = orch.plan_next_batch(batch_size=10)
    assert planner.calls == 1
    assert [s.category for s in selections] == ["prompt_injection", "tool_misuse"]


@pytest.mark.unit
def test_plan_next_batch_deterministic_fallback(
    session_factory: Callable[[], Session],
) -> None:
    """No planner client → deterministic heuristic returns batch_size selections
    from the canonical 8×9 product."""
    orch, _ = _build(session_factory, planner=None)
    selections = orch.plan_next_batch(batch_size=5)
    assert len(selections) == 5
    # Every selection must be in the canonical category × strategy product.
    from agentforge.orchestrator.coverage import CATEGORIES, STRATEGIES

    valid = {(c, s) for c in CATEGORIES for s in STRATEGIES}
    for sel in selections:
        assert (sel.category, sel.strategy) in valid
        assert "deterministic" in sel.rationale


@pytest.mark.unit
def test_step_calls_all_five_roles_in_order(
    session_factory: Callable[[], Session],
) -> None:
    """`step()` invokes Red Team → Target Adapter → Internal Judge → External Judge → Coverage in the master-plan §8.1 sequence."""
    planner = FakePlanner([CategoryStrategy(category="prompt_injection", strategy="single_turn")])
    orch, bag = _build(session_factory, planner=planner)
    result = orch.step(batch_size=1)
    assert result.attacks_executed == 1
    rt: FakeRedTeam = bag["redteam"]
    ta: FakeTargetAdapter = bag["target_adapter"]
    iv: FakeInternalJudge = bag["internal"]
    ev: FakeExternalJudge = bag["external"]
    # The five expected roles (red team, target, internal judge, external judge,
    # coverage) were each called exactly once for the single selection.
    assert len(rt.calls) == 1
    assert len(ta.calls) == 1
    assert len(iv.calls) == 1
    assert len(ev.calls) == 1


@pytest.mark.unit
def test_step_persists_coverage(
    session_factory: Callable[[], Session],
) -> None:
    """After one passing step, the coverage matrix row for `(category, strategy)` shows `attempts=1`, `passes=1` (persisted to `coverage_cells`)."""
    planner = FakePlanner([CategoryStrategy(category="prompt_injection", strategy="single_turn")])
    orch, bag = _build(session_factory, planner=planner)
    orch.step(batch_size=1)
    cov: CoverageMatrix = bag["coverage"]
    cell = cov.get("prompt_injection", "single_turn")
    assert cell.attempts == 1
    # External judge fake returns all_pass=True → cell passes.
    assert cell.passes == 1
    assert cell.failures == 0


@pytest.mark.unit
def test_step_skips_remaining_jobs_when_budget_halts_mid_batch(
    session_factory: Callable[[], Session],
) -> None:
    """A halt mid-batch must short-circuit remaining selections without
    raising or losing the halt reason."""
    planner = FakePlanner(
        [
            CategoryStrategy(category="prompt_injection", strategy="single_turn"),
            CategoryStrategy(category="tool_misuse", strategy="crescendo"),
            CategoryStrategy(category="data_exfiltration", strategy="role_play"),
        ]
    )
    # Tight smoke ceiling — the first attack's DEFAULT_PER_ATTACK_COST_USD tick
    # plus the per-attack default cost will exceed it after one or two attacks.
    cfg = BudgetConfig(  # type: ignore[call-arg]
        BUDGET_SMOKE_USD=Decimal("0.0005"),  # below default 0.001 cost
        BUDGET_SEEDED_USD=Decimal("100.00"),
        BUDGET_EXPLORATORY_USD=Decimal("0.0005"),
        BUDGET_PER_DAY_USD=Decimal("1000.00"),
        BUDGET_HALT_AFTER_N_NULL_RUNS=9999,
        BUDGET_NULL_RUN_SPEND_THRESHOLD_USD=Decimal("1000.00"),
        BUDGET_PER_ATTACK_TIMEOUT_S=60,
        BUDGET_TARGET_ERROR_RATE_HALT=0.99,
    )
    orch, bag = _build(session_factory, planner=planner, budget_cfg=cfg)
    result = orch.step(batch_size=3)
    # The first attack runs, then the BudgetGuard halts on cost ceiling.
    # Remaining selections are skipped.
    assert result.attacks_executed == 1
    assert result.halted is True
    assert result.halt_reason == HaltReason.BUDGET_EXPLORATORY_EXCEEDED
    ta: FakeTargetAdapter = bag["target_adapter"]
    assert len(ta.calls) == 1


@pytest.mark.unit
def test_target_adapter_exception_becomes_error_response(
    session_factory: Callable[[], Session],
) -> None:
    """A raised exception from `target_adapter.execute` is translated to a synthetic `AdapterResponse(error="target_adapter_exception: ...")` instead of aborting the run."""
    planner = FakePlanner([CategoryStrategy(category="prompt_injection", strategy="single_turn")])
    target = FakeTargetAdapter(raise_for_strategy="single_turn")
    orch, bag = _build(session_factory, planner=planner, target_adapter=target)
    result = orch.step(batch_size=1)
    # Exception did NOT abort the run.
    assert result.attacks_executed == 1
    # External judge was still called with a response carrying error.
    ev: FakeExternalJudge = bag["external"]
    assert len(ev.calls) == 1
    _attack, response, _expected = ev.calls[0]
    assert response.error is not None
    assert "target_adapter_exception" in response.error


@pytest.mark.unit
def test_failed_external_verdict_triggers_doc_write_report(
    session_factory: Callable[[], Session],
) -> None:
    """A failing External Final verdict calls `DocumentationAgent.write_report` exactly once and flips the cell to `failures=1`."""
    planner = FakePlanner([CategoryStrategy(category="prompt_injection", strategy="single_turn")])
    external = FakeExternalJudge(all_pass=False)
    orch, bag = _build(session_factory, planner=planner, external=external)
    result = orch.step(batch_size=1)
    assert result.findings_written == 1
    doc: FakeDocAgent = bag["doc"]
    assert len(doc.calls) == 1
    # And the failure flipped the cell to failures=1.
    cov: CoverageMatrix = bag["coverage"]
    cell = cov.get("prompt_injection", "single_turn")
    assert cell.attempts == 1
    assert cell.failures == 1


@pytest.mark.unit
def test_passed_external_verdict_does_not_call_doc_agent(
    session_factory: Callable[[], Session],
) -> None:
    """A passing External Final verdict NEVER calls `DocumentationAgent.write_report` (no spurious VR-#### writes)."""
    planner = FakePlanner([CategoryStrategy(category="prompt_injection", strategy="single_turn")])
    orch, bag = _build(session_factory, planner=planner)
    orch.step(batch_size=1)
    doc: FakeDocAgent = bag["doc"]
    assert doc.calls == []
