"""Orchestrator prompt tests — master plan §8.1."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from agentforge.config import BudgetConfig
from agentforge.judge.external_final import ExternalFinalJudge
from agentforge.judge.internal_progress import InternalProgressJudge
from agentforge.judge.rubrics import RubricRegistry
from agentforge.orchestrator.budget_guard import BudgetGuard
from agentforge.orchestrator.coverage import CoverageMatrix
from agentforge.orchestrator.orchestrator import (
    CategoryStrategy,
    OrchestratorAgent,
    OrchestratorAnthropicClient,
    PlannerResponse,
)
from agentforge.orchestrator.prompts import (
    ORCHESTRATOR_SYSTEM_PROMPT,
    ORCHESTRATOR_USER_PROMPT_TEMPLATE,
)


class _CapturingClient:
    """Records the (system, user) it was last called with and returns 3 selections."""

    def __init__(self) -> None:
        self.last_system: str | None = None
        self.last_user: str | None = None

    def plan_batch(self, system: str, user: str) -> PlannerResponse:
        self.last_system = system
        self.last_user = user
        return PlannerResponse(
            selections=[
                CategoryStrategy(category="prompt_injection", strategy="single_turn", rationale="a"),
                CategoryStrategy(category="tool_misuse", strategy="crescendo", rationale="b"),
                CategoryStrategy(category="data_exfiltration", strategy="role_play", rationale="c"),
            ]
        )


def _make_orch(
    session_factory: Callable[[], Session],
    client: OrchestratorAnthropicClient | None,
) -> OrchestratorAgent:
    cfg = BudgetConfig(  # type: ignore[call-arg]
        BUDGET_SMOKE_USD=Decimal("1.00"),
        BUDGET_SEEDED_USD=Decimal("5.00"),
        BUDGET_EXPLORATORY_USD=Decimal("10.00"),
        BUDGET_PER_DAY_USD=Decimal("25.00"),
        BUDGET_HALT_AFTER_N_NULL_RUNS=999,
        BUDGET_NULL_RUN_SPEND_THRESHOLD_USD=Decimal("1000.00"),
        BUDGET_PER_ATTACK_TIMEOUT_S=60,
        BUDGET_TARGET_ERROR_RATE_HALT=0.99,
    )
    guard = BudgetGuard(cfg, run_type="exploratory")
    coverage = CoverageMatrix(session_factory)
    rubric_registry = RubricRegistry()
    internal = InternalProgressJudge(rubric_registry=rubric_registry)
    external = ExternalFinalJudge(rubric_registry=rubric_registry)
    # Red team / target / doc are not exercised here; pass None as placeholder
    # via cast — these tests only call plan_next_batch which never touches them.
    return OrchestratorAgent(
        redteam=object(),  # type: ignore[arg-type]
        target_adapter=object(),  # type: ignore[arg-type]
        internal_judge=internal,
        external_judge=external,
        documentation=object(),  # type: ignore[arg-type]
        coverage=coverage,
        budget_guard=guard,
        anthropic_client=client,
        run_id="00000000-0000-0000-0000-000000000001",
    )


@pytest.mark.unit
def test_template_renders_with_expected_fields(
    session_factory: Callable[[], Session],
) -> None:
    """The user prompt template must accept every field named in the spec."""
    text = ORCHESTRATOR_USER_PROMPT_TEMPLATE.format(
        coverage_snapshot_json="[]",
        open_findings_summary="[]",
        target_fingerprint="abc",
        recent_fingerprint_change_at="2026-05-13T00:00:00+00:00",
        budget_state_json="{}",
        batch_size=10,
    )
    assert "batch_size: 10" in text
    assert "target_fingerprint: abc" in text
    assert "coverage_snapshot" in text
    assert "budget_state" in text
    # System prompt is non-empty and names the orchestrator role.
    assert "Orchestrator" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "STRICT JSON" in ORCHESTRATOR_SYSTEM_PROMPT


@pytest.mark.unit
def test_planner_response_json_shape(
    session_factory: Callable[[], Session],
) -> None:
    """PlannerResponse parses the schema the system prompt advertises."""
    raw = json.dumps(
        {
            "selections": [
                {"category": "prompt_injection", "strategy": "single_turn", "rationale": "x"}
            ],
            "halt_reasons": [],
        }
    )
    resp = PlannerResponse.model_validate_json(raw)
    assert len(resp.selections) == 1
    assert resp.selections[0].category == "prompt_injection"
    assert resp.halt_reasons == []
    # Round-trip preserves schema.
    again = PlannerResponse.model_validate_json(resp.model_dump_json())
    assert again == resp


@pytest.mark.unit
def test_batch_size_honored_when_planner_returns_more(
    session_factory: Callable[[], Session],
) -> None:
    """plan_next_batch must cap selections at batch_size even if the planner
    returns more."""
    client = _CapturingClient()
    orch = _make_orch(session_factory, client)
    selections = orch.plan_next_batch(batch_size=2)
    assert len(selections) == 2
    # The full system + user prompt was forwarded to the client.
    assert client.last_system == ORCHESTRATOR_SYSTEM_PROMPT
    assert client.last_user is not None and "batch_size: 2" in client.last_user
