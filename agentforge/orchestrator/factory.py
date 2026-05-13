"""Orchestrator composition factory -- builds the full multi-agent loop from settings.

This module is the first place in the codebase where all seven agent deps
are constructed together. Prior to AgDR-0016 the platform shipped with
working individual agents but no composition layer: ``tb attack`` was a
stub. The factory closes that gap.

Construction order (each step depends on the prior):

1. ``MainConfig`` settings (singleton via ``get_settings``)
2. SQLAlchemy session factory (lazy singleton via ``get_session_factory``)
3. Red Team client (OpenRouter for AgDR-0013 default; Anthropic fallback)
4. RedTeamAgent (seeds + 9-mutator stack + lineage + client)
5. RubricRegistry (stateless)
6. InternalProgressJudge + HaikuQuickVerdictClient
7. ExternalFinalJudge + SonnetJudgeClient
8. DocumentationAgent + SonnetDocClient + repo / vc_index / tagger / curator
9. CoverageMatrix (session-factory backed)
10. BudgetGuard (BudgetConfig + RunType)
11. SonnetPlannerClient (for the orchestrator's strategic LLM step)
12. OrchestratorAgent with all of the above

Live LLM calls happen inside ``OrchestratorAgent.step()``; the factory itself
performs no network I/O.

Each Anthropic wrapper falls back to deterministic behavior if its API call
fails -- a network error halts neither the loop nor the factory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import uuid4

from agentforge.config import MainConfig, get_settings
from agentforge.documentation.agent import DocumentationAgent
from agentforge.documentation.regression_curator import RegressionCurator
from agentforge.documentation.tagger import Tagger
from agentforge.documentation.vulnerability_class import VulnerabilityClassIndex
from agentforge.judge.external_final import ExternalFinalJudge
from agentforge.judge.internal_progress import InternalProgressJudge
from agentforge.judge.rubrics import RubricRegistry
from agentforge.llm.anthropic_clients import (
    HaikuQuickVerdictClient,
    SonnetDocClient,
    SonnetJudgeClient,
    SonnetPlannerClient,
)
from agentforge.memory.db import get_session_factory
from agentforge.memory.repo import MemoryRepo
from agentforge.orchestrator.budget_guard import BudgetGuard
from agentforge.orchestrator.coverage import CoverageMatrix
from agentforge.orchestrator.orchestrator import OrchestratorAgent, TargetExecutor
from agentforge.pricing import PricingTable
from agentforge.redteam.agent import RedTeamAgent
from agentforge.redteam.anthropic_client import RedTeamAnthropicClient
from agentforge.redteam.lineage import AttackLineage
from agentforge.redteam.mutators.base import MutatorStack
from agentforge.redteam.mutators.encoders import (
    Base64Encoder,
    LeetspeakEncoder,
    ZeroWidthSplitter,
)
from agentforge.redteam.mutators.persuasion import (
    AuthorityMutator,
    TrustMutator,
    UrgencyMutator,
)
from agentforge.redteam.mutators.role_wrap import (
    RoleWrapAdmin,
    RoleWrapAuditor,
    RoleWrapDoctor,
)
from agentforge.redteam.openrouter_client import RedTeamOpenRouterClient
from agentforge.redteam.seed_catalog import SeedCatalog

RunTypeLiteral = Literal["smoke", "seeded", "exploratory"]


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _default_reports_dir() -> Path:
    return _project_root() / "reports"


def _default_regression_dir() -> Path:
    return _project_root() / "evals" / "regression"


def _build_default_mutator_stack() -> MutatorStack:
    """Compose the canonical 9-mutator stack used by the Red Team Agent.

    Matches the test fixture in ``tests/unit/redteam/test_agent_generate.py``.
    Document-smuggle mutators are intentionally excluded -- they emit bytes
    payloads for indirect-injection attacks and require a different code path.
    """
    return MutatorStack(
        [
            Base64Encoder(),
            LeetspeakEncoder(),
            ZeroWidthSplitter(),
            RoleWrapDoctor(),
            RoleWrapAdmin(),
            RoleWrapAuditor(),
            UrgencyMutator(),
            AuthorityMutator(),
            TrustMutator(),
        ]
    )


def _build_redteam_client(
    settings: MainConfig,
) -> RedTeamOpenRouterClient | RedTeamAnthropicClient | None:
    """Pick the Red Team client by ``REDTEAM_PROVIDER``.

    Returns ``None`` if no provider has its API key configured -- the
    RedTeamAgent then runs in deterministic-mutator-only mode.
    """
    provider = settings.redteam_provider
    if provider == "openrouter":
        if not settings.openrouter.api_key:
            return None
        return RedTeamOpenRouterClient(
            api_key=settings.openrouter.api_key,
            model=settings.openrouter.redteam_model,
            base_url=settings.openrouter.base_url,
            fallback_model=settings.openrouter.redteam_fallback_model or None,
            http_referer=settings.openrouter.http_referer,
            x_title=settings.openrouter.x_title,
        )
    if provider == "anthropic":
        api_key = settings.anthropic.api_key_redteam or settings.anthropic.api_key
        if not api_key:
            return None
        return RedTeamAnthropicClient(api_key=api_key, model=settings.anthropic.redteam_model)
    # "fireworks" intentionally unhandled -- per AgDR-0013 the provider is a
    # historical placeholder; activating it would require writing the client.
    return None


def build_orchestrator(
    target_adapter: TargetExecutor,
    *,
    run_type: RunTypeLiteral = "smoke",
    run_id: str | None = None,
    settings: MainConfig | None = None,
    reports_dir: Path | None = None,
    regression_dir: Path | None = None,
) -> OrchestratorAgent:
    """Construct a fully wired ``OrchestratorAgent``.

    Parameters
    ----------
    target_adapter:
        The TargetExecutor implementation. Production: ``SidecarDirectAdapter``.
        Tests: any object with a sync ``execute(attack) -> AdapterResponse``.
    run_type:
        Budget ceiling band. ``smoke`` is the lowest-cost; use it for the
        first end-to-end verification. ``seeded`` and ``exploratory`` widen
        the ceiling.
    run_id:
        Optional UUID string for cross-trace correlation. A fresh UUID is
        minted if omitted.
    settings:
        Override the singleton ``MainConfig`` -- mainly for tests.
    reports_dir / regression_dir:
        Override default filesystem layout (under ``./reports`` and
        ``./evals/regression``).
    """
    cfg = settings or get_settings()
    rid = run_id or str(uuid4())

    # ---- Database session factory (lazy) ---------------------------------
    session_factory = get_session_factory()

    # ---- Red Team -------------------------------------------------------
    redteam_client = _build_redteam_client(cfg)
    redteam = RedTeamAgent(
        SeedCatalog(),
        _build_default_mutator_stack(),
        AttackLineage(),
        anthropic_client=redteam_client,
        rng_seed=0,
    )

    # ---- Rubric registry (shared by both judges) -------------------------
    rubric_registry = RubricRegistry()

    # ---- Internal Progress Judge (Haiku, optional) -----------------------
    haiku_client = (
        HaikuQuickVerdictClient(
            api_key=cfg.anthropic.api_key,
            model=cfg.anthropic.fast_model,
        )
        if cfg.anthropic.api_key
        else None
    )
    internal_judge = InternalProgressJudge(
        rubric_registry=rubric_registry,
        anthropic_client=haiku_client,
    )

    # ---- External Final Judge (Sonnet, optional) -------------------------
    sonnet_judge_client = (
        SonnetJudgeClient(
            api_key=cfg.anthropic.api_key_judge or cfg.anthropic.api_key,
            model=cfg.anthropic.orchestrator_model,
        )
        if (cfg.anthropic.api_key_judge or cfg.anthropic.api_key)
        else None
    )
    external_judge = ExternalFinalJudge(
        rubric_registry=rubric_registry,
        anthropic_client=sonnet_judge_client,
        model_name=cfg.anthropic.orchestrator_model,
    )

    # ---- Documentation Agent (Sonnet, optional) --------------------------
    sonnet_doc_client = (
        SonnetDocClient(
            api_key=cfg.anthropic.api_key,
            model=cfg.anthropic.orchestrator_model,
        )
        if cfg.anthropic.api_key
        else None
    )
    doc_reports_dir = reports_dir or _default_reports_dir()
    doc_regression_dir = regression_dir or _default_regression_dir()
    documentation = DocumentationAgent(
        anthropic_client=sonnet_doc_client,
        vc_index=VulnerabilityClassIndex(session_factory),
        tagger=Tagger(),
        regression_curator=RegressionCurator(doc_regression_dir),
        reports_dir=doc_reports_dir,
        repo=MemoryRepo(session_factory),
    )

    # ---- Coverage Matrix + Budget Guard ----------------------------------
    coverage = CoverageMatrix(session_factory=session_factory)
    budget_guard = BudgetGuard(budget_config=cfg.budget, run_type=run_type)

    # ---- Orchestrator planner client (Sonnet, optional) ------------------
    sonnet_planner_client = (
        SonnetPlannerClient(
            api_key=cfg.anthropic.api_key,
            model=cfg.anthropic.orchestrator_model,
        )
        if cfg.anthropic.api_key
        else None
    )

    # ---- Pricing table for real-token cost (sub-plan Next03 §4.3, AgDR-0021)
    pricing_path = _project_root() / "config" / "pricing.yml"
    pricing = PricingTable.from_yaml(pricing_path) if pricing_path.is_file() else None

    # Map agent_role → wrapper-with-.last_usage. Red Team uses a separate
    # OpenRouter client and its cost is $0 on the :free tier; we leave it
    # to the class-level estimate for now.
    usage_sources: dict[str, object] = {}
    if haiku_client is not None:
        usage_sources["internal_judge"] = haiku_client
    if sonnet_judge_client is not None:
        usage_sources["external_judge"] = sonnet_judge_client
    if sonnet_doc_client is not None:
        usage_sources["documentation"] = sonnet_doc_client
    if sonnet_planner_client is not None:
        usage_sources["orchestrator_planner"] = sonnet_planner_client

    return OrchestratorAgent(
        redteam=redteam,
        target_adapter=target_adapter,
        internal_judge=internal_judge,
        external_judge=external_judge,
        documentation=documentation,
        coverage=coverage,
        budget_guard=budget_guard,
        anthropic_client=sonnet_planner_client,
        run_id=rid,
        target_fingerprint="",  # populated by orchestrator on first run; sentinel here
        recent_fingerprint_change_at=None,
        open_findings=None,
        # AgDR-0017: wire the persistence layer so step() updates the dashboard.
        session_factory=session_factory,
        run_type=run_type,
        # AgDR-0021: real per-call token-cost path.
        pricing=pricing,
        usage_sources=usage_sources,
    )


__all__ = ["build_orchestrator", "RunTypeLiteral"]
