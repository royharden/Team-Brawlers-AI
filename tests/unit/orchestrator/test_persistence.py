"""Orchestrator persistence layer (AgDR-0017).

Verifies that ``OrchestratorAgent.step()`` writes Run / AttackJob /
AttackTrace / Verdict / CostLedgerEntry rows when a ``session_factory``
is injected. Uses an in-memory SQLite with all tables created via the
declarative metadata -- no Alembic, no on-disk side effects.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from agentforge.documentation.agent import DocumentationAgent
from agentforge.documentation.regression_curator import RegressionCurator
from agentforge.documentation.tagger import Tagger
from agentforge.documentation.vulnerability_class import VulnerabilityClassIndex
from agentforge.judge.external_final import ExternalFinalJudge
from agentforge.judge.internal_progress import InternalProgressJudge
from agentforge.judge.rubrics import RubricRegistry
from agentforge.memory.models import (
    AttackJob as AttackJobRow,
)
from agentforge.memory.models import (
    AttackTrace as AttackTraceRow,
)
from agentforge.memory.models import (
    Base,
    CostLedgerEntry,
    CoverageCellRow,
    Run,
    Verdict,
)
from agentforge.memory.repo import MemoryRepo
from agentforge.memory.schemas import AdapterResponse, MutatedAttack
from agentforge.orchestrator.budget_guard import BudgetGuard
from agentforge.orchestrator.coverage import CoverageMatrix
from agentforge.orchestrator.orchestrator import (
    CategoryStrategy,
    OrchestratorAgent,
)
from agentforge.redteam.agent import RedTeamAgent
from agentforge.redteam.lineage import AttackLineage
from agentforge.redteam.mutators.base import MutatorStack
from agentforge.redteam.mutators.role_wrap import RoleWrapDoctor
from agentforge.redteam.seed_catalog import SeedCatalog

# --------------------------------------------------------------------------- harness


@pytest.fixture
def session_factory(tmp_path: Any) -> sessionmaker[Session]:
    """In-memory SQLite with the full schema; tables created from metadata."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


class _StaticPlanner:
    """A planner client that returns a fixed (category, strategy) selection."""

    def __init__(self, category: str = "prompt_injection", strategy: str = "single_turn") -> None:
        self._category = category
        self._strategy = strategy

    def plan_batch(self, system: str, user: str) -> Any:
        from agentforge.orchestrator.orchestrator import PlannerResponse

        return PlannerResponse(
            selections=[
                CategoryStrategy(category=self._category, strategy=self._strategy, rationale="test")
            ],
            halt_reasons=[],
        )


class _ScriptedAdapter:
    """Returns a canned ``AdapterResponse`` -- no network."""

    name = "scripted"

    def execute(self, attack: MutatedAttack) -> AdapterResponse:
        return AdapterResponse(
            attack_id=uuid.UUID(attack.attack_id) if attack.attack_id else uuid.uuid4(),
            status_code=200,
            body_text="target defended",
            body_json={"verifier_status": "passed", "claims": []},
            latency_ms=512.0,
            cost_usd=0.0,
        )


def _build_orchestrator(
    session_factory: sessionmaker[Session],
    *,
    run_id: str | None = None,
    run_type: str = "smoke",
) -> OrchestratorAgent:
    """Compose an orchestrator with persistence on. Each agent gets the same
    in-memory SQLite session factory.
    """
    rid = run_id or str(uuid.uuid4())
    redteam = RedTeamAgent(
        SeedCatalog(),
        MutatorStack([RoleWrapDoctor()]),
        AttackLineage(),
        anthropic_client=None,  # deterministic-only -- no Dolphin call in unit test
    )
    rubric_registry = RubricRegistry()
    internal_judge = InternalProgressJudge(rubric_registry=rubric_registry)
    external_judge = ExternalFinalJudge(rubric_registry=rubric_registry)
    documentation = DocumentationAgent(
        anthropic_client=None,
        vc_index=VulnerabilityClassIndex(session_factory),
        tagger=Tagger(),
        regression_curator=RegressionCurator(_temp_regression_dir()),
        reports_dir=_temp_reports_dir(),
        repo=MemoryRepo(session_factory),
    )
    coverage = CoverageMatrix(session_factory=session_factory)
    from agentforge.config import BudgetConfig

    budget_guard = BudgetGuard(
        budget_config=BudgetConfig.model_construct(
            smoke_usd=Decimal("1.00"),
            seeded_usd=Decimal("5.00"),
            exploratory_usd=Decimal("10.00"),
            per_day_usd=Decimal("25.00"),
            halt_after_n_null_runs=25,
            null_run_spend_threshold_usd=Decimal("3.00"),
            per_attack_timeout_s=60,
            target_error_rate_halt=0.20,
        ),
        run_type=run_type,
    )
    return OrchestratorAgent(
        redteam=redteam,
        target_adapter=_ScriptedAdapter(),
        internal_judge=internal_judge,
        external_judge=external_judge,
        documentation=documentation,
        coverage=coverage,
        budget_guard=budget_guard,
        anthropic_client=_StaticPlanner(),
        run_id=rid,
        session_factory=session_factory,
        run_type=run_type,
    )


def _temp_reports_dir() -> Any:
    """Doc Agent requires a real dir; tmp_path fixture would be cleaner but the
    agent only writes if a finding is emitted -- in this unit test we never
    fail a rubric so the dir stays empty.
    """
    from pathlib import Path
    from tempfile import mkdtemp

    return Path(mkdtemp(prefix="orchestrator_test_reports_"))


def _temp_regression_dir() -> Any:
    from pathlib import Path
    from tempfile import mkdtemp

    return Path(mkdtemp(prefix="orchestrator_test_regression_"))


# --------------------------------------------------------------------------- tests


@pytest.mark.unit
def test_persistence_off_when_session_factory_none() -> None:
    """Default construction (no session_factory) leaves DB writes off.

    Confirms the additive design: existing tests + memory-only callers see
    no behavior change.
    """
    # Build a minimal orchestrator with session_factory=None (the default).
    redteam = RedTeamAgent(
        SeedCatalog(),
        MutatorStack([RoleWrapDoctor()]),
        AttackLineage(),
        anthropic_client=None,
    )
    rubric_registry = RubricRegistry()
    from agentforge.config import BudgetConfig

    orch = OrchestratorAgent(
        redteam=redteam,
        target_adapter=_ScriptedAdapter(),
        internal_judge=InternalProgressJudge(rubric_registry=rubric_registry),
        external_judge=ExternalFinalJudge(rubric_registry=rubric_registry),
        documentation=DocumentationAgent(
            anthropic_client=None,
            vc_index=VulnerabilityClassIndex(lambda: None),  # type: ignore[arg-type]
            tagger=Tagger(),
            regression_curator=RegressionCurator(_temp_regression_dir()),
            reports_dir=_temp_reports_dir(),
            repo=None,
        ),
        coverage=CoverageMatrix(session_factory=lambda: None),  # type: ignore[arg-type]
        budget_guard=BudgetGuard(
            budget_config=BudgetConfig.model_construct(
                smoke_usd=Decimal("1.0"),
                seeded_usd=Decimal("5.0"),
                exploratory_usd=Decimal("10.0"),
                per_day_usd=Decimal("25.0"),
                halt_after_n_null_runs=25,
                null_run_spend_threshold_usd=Decimal("3.0"),
                per_attack_timeout_s=60,
                target_error_rate_halt=0.20,
            ),
            run_type="smoke",
        ),
        run_id=str(uuid.uuid4()),
        # session_factory NOT passed -- defaults to None.
    )
    # No exception, no DB IO. Calling end_run() with no factory is also a no-op.
    orch.end_run()


@pytest.mark.unit
def test_step_writes_run_and_attack_job(session_factory: sessionmaker[Session]) -> None:
    """One step() iteration inserts exactly one Run + one AttackJob row."""
    run_id = str(uuid.uuid4())
    orch = _build_orchestrator(session_factory, run_id=run_id)

    s = session_factory()
    assert s.query(Run).count() == 0
    s.close()

    orch.step(batch_size=1)

    s = session_factory()
    runs = s.query(Run).all()
    jobs = s.query(AttackJobRow).all()
    s.close()

    assert len(runs) == 1
    assert runs[0].id == run_id
    assert runs[0].run_type == "smoke"
    assert runs[0].status == "running"  # end_run not yet called
    assert len(jobs) == 1
    assert jobs[0].run_id == run_id
    assert jobs[0].category == "prompt_injection"
    assert jobs[0].strategy == "single_turn"
    assert jobs[0].status == "completed"  # upsert by step() after redteam+adapter ran


@pytest.mark.unit
def test_step_writes_attack_trace_and_verdicts(session_factory: sessionmaker[Session]) -> None:
    """One step() inserts one trace + two verdicts (internal + external)."""
    orch = _build_orchestrator(session_factory)
    orch.step(batch_size=1)

    s = session_factory()
    traces = s.query(AttackTraceRow).all()
    verdicts = s.query(Verdict).all()
    s.close()

    assert len(traces) == 1
    assert traces[0].latency_ms == 512  # scripted adapter
    assert traces[0].target_error is None
    assert len(verdicts) == 2
    layers = {v.layer for v in verdicts}
    assert layers == {"internal_progress", "external_final"}


@pytest.mark.unit
def test_step_writes_cost_ledger_rows(session_factory: sessionmaker[Session]) -> None:
    """One step() inserts cost_ledger rows for each agent role that ran."""
    orch = _build_orchestrator(session_factory)
    orch.step(batch_size=1)

    s = session_factory()
    cost_rows = s.query(CostLedgerEntry).all()
    s.close()

    assert len(cost_rows) >= 4  # redteam + adapter + internal_judge + external_judge
    roles = {r.agent_role for r in cost_rows}
    assert "redteam" in roles
    assert "adapter" in roles
    assert "internal_judge" in roles
    assert "external_judge" in roles


@pytest.mark.unit
def test_end_run_finalizes_status_and_total_cost(session_factory: sessionmaker[Session]) -> None:
    """end_run() updates ended_at, status, halt_reason, and total_cost_usd."""
    orch = _build_orchestrator(session_factory)
    orch.step(batch_size=1)
    orch.end_run(status="completed", halt_reason=None)

    s = session_factory()
    run = s.query(Run).one()
    s.close()

    assert run.status == "completed"
    assert run.ended_at is not None
    # total_cost_usd should equal the sum of cost_ledger entries.
    s2 = session_factory()
    expected_total = sum(
        (Decimal(str(r.cost_usd)) for r in s2.query(CostLedgerEntry).all()), Decimal("0")
    )
    s2.close()
    assert Decimal(str(run.total_cost_usd)) == expected_total


@pytest.mark.unit
def test_coverage_cells_persisted_too(session_factory: sessionmaker[Session]) -> None:
    """CoverageMatrix.update() runs inside step(); cell row should exist."""
    orch = _build_orchestrator(session_factory)
    orch.step(batch_size=1)

    s = session_factory()
    cells = s.query(CoverageCellRow).all()
    s.close()

    assert len(cells) == 1
    cell = cells[0]
    assert cell.category == "prompt_injection"
    assert cell.strategy == "single_turn"
    assert cell.attempts == 1
    assert cell.last_attempt_at is not None


@pytest.mark.unit
def test_persistence_idempotent_on_second_step(session_factory: sessionmaker[Session]) -> None:
    """A second step() reuses the same Run row but creates new AttackJob/Trace."""
    orch = _build_orchestrator(session_factory)
    orch.step(batch_size=1)
    orch.step(batch_size=1)

    s = session_factory()
    runs = s.query(Run).all()
    jobs = s.query(AttackJobRow).all()
    s.close()

    assert len(runs) == 1  # single run id, persisted once
    assert len(jobs) == 2  # one job per step
