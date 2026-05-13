"""Cost projection model + payload builder — sub-plan Next03 §3.3.

The four-scale projection (100 / 1K / 10K / 100K test runs) is the PRD's
"AI cost analysis" hard-gate deliverable. Originally lived only in
``scripts/cost_extrapolate.py``; this module extracts the pure-function core
so the FastAPI ``/v1/cost/projections`` route can compute fresh projections
from `config/pricing.yml` + `cost_ledger` on every request, without
depending on a JSON file the operator had to remember to regenerate.

Decimal arithmetic end-to-end — never floats on the cost path. The script
keeps its own ``main()`` for offline runs that emit
``evals/results/cost_extrapolate_*.json``; both paths reuse this module's
``build_projections_payload``.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agentforge.memory.models import CostLedgerEntry
from agentforge.pricing import PricingTable

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRICING_PATH = REPO_ROOT / "config" / "pricing.yml"


# ---------------------------------------------------------------------------
# Per-role assumption + per-scale overlay (verbatim from
# scripts/cost_extrapolate.py — kept here as the canonical source).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoleAssumption:
    """Per-role token + call-count assumption used to model cost."""

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    calls_per_run: Decimal


DEFAULT_ASSUMPTIONS: dict[str, RoleAssumption] = {
    "orchestrator": RoleAssumption(
        provider="anthropic",
        model="claude-sonnet-4-6",
        input_tokens=600,
        output_tokens=200,
        calls_per_run=Decimal("0.1"),
    ),
    "red_team": RoleAssumption(
        provider="openrouter",
        # AgDR-0024 reverted AgDR-0022's swap — the `:free` Dolphin still
        # works (just rate-limits upstream). The OpenAI-direct fallback
        # client (AgDR-0024) is what we'd flip the assumption to if the
        # operator wants to model paid fallback spend at the 100K scale.
        model="cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
        input_tokens=800,
        output_tokens=400,
        calls_per_run=Decimal("1"),
    ),
    "internal_judge": RoleAssumption(
        provider="anthropic",
        model="claude-haiku-4-6",
        input_tokens=1000,
        output_tokens=100,
        calls_per_run=Decimal("0.3"),
    ),
    "external_judge": RoleAssumption(
        provider="anthropic",
        model="claude-sonnet-4-6",
        input_tokens=1500,
        output_tokens=200,
        calls_per_run=Decimal("5"),
    ),
    "documentation": RoleAssumption(
        provider="anthropic",
        model="claude-sonnet-4-6",
        input_tokens=2000,
        output_tokens=600,
        calls_per_run=Decimal("0.1"),
    ),
}


@dataclass(frozen=True)
class ScaleOverlay:
    n_runs: int
    infra_monthly_usd: Decimal
    per_call_overhead: Decimal
    external_judge_batching_factor: Decimal
    architecture_notes: str


SCALE_OVERLAYS: list[ScaleOverlay] = [
    ScaleOverlay(
        n_runs=100,
        infra_monthly_usd=Decimal("0"),
        per_call_overhead=Decimal("1.00"),
        external_judge_batching_factor=Decimal("1"),
        architecture_notes=(
            "In-process SQLite (WAL), single-process orchestrator. No sharding, no "
            "queueing layer. Bottleneck is developer iteration speed, not infra."
        ),
    ),
    ScaleOverlay(
        n_runs=1000,
        infra_monthly_usd=Decimal("0"),
        per_call_overhead=Decimal("1.05"),
        external_judge_batching_factor=Decimal("1"),
        architecture_notes=(
            "Still single-process SQLite. Langfuse tracing overhead becomes "
            "noticeable (~5%). Cost-tracker accuracy starts to matter; rerun the "
            "BudgetGuard's cost-without-signal halt assumptions if Red Team yield "
            "drops below 10%."
        ),
    ),
    ScaleOverlay(
        n_runs=10000,
        infra_monthly_usd=Decimal("50"),
        per_call_overhead=Decimal("1.10"),
        external_judge_batching_factor=Decimal("1"),
        architecture_notes=(
            "Postgres migration required (SQLite single-writer bottleneck). "
            "Worker pool replaces synchronous step loop. Per-target sharding "
            "starts paying off. Adds ~$50/mo Postgres + ~10% queue-serialization "
            "overhead. Nightly cron via GH Actions or APScheduler."
        ),
    ),
    ScaleOverlay(
        n_runs=100000,
        infra_monthly_usd=Decimal("300"),
        per_call_overhead=Decimal("1.15"),
        external_judge_batching_factor=Decimal("0.70"),
        architecture_notes=(
            "Queueing layer (Redis/Celery or AWS SQS), per-target sharding, "
            "External-Judge batching (5 rubrics per call → 30% cost reduction "
            "in that role). Adds ~$300/mo infra + ~15% per-call overhead from "
            "batching coordination. Live-target rate-limit becomes the real "
            "bottleneck; BudgetGuard's target-error-rate halt is load-bearing."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Pure projection arithmetic.
# ---------------------------------------------------------------------------


@dataclass
class ScaleProjection:
    n_runs: int
    infra_monthly_usd: Decimal
    per_run_usd: Decimal
    total_usd: Decimal
    architecture_notes: str
    by_role_usd: dict[str, Decimal] = field(default_factory=dict)


def _quantize(value: Decimal, places: str = "0.000001") -> Decimal:
    return value.quantize(Decimal(places))


def project_per_role_cost(
    role: str,
    assumption: RoleAssumption,
    pricing: PricingTable,
    overlay: ScaleOverlay,
) -> Decimal:
    """USD cost contributed by one role for ONE platform test run."""
    per_call_cost = pricing.cost_for_call(
        provider=assumption.provider,
        model=assumption.model,
        input_tokens=assumption.input_tokens,
        output_tokens=assumption.output_tokens,
    )
    calls = assumption.calls_per_run
    if role == "external_judge":
        calls = calls * overlay.external_judge_batching_factor
    return per_call_cost * calls * overlay.per_call_overhead


def build_scale_projection(
    pricing: PricingTable,
    assumptions: dict[str, RoleAssumption],
    overlay: ScaleOverlay,
) -> ScaleProjection:
    by_role: dict[str, Decimal] = {}
    per_run = Decimal("0")
    for role, assumption in assumptions.items():
        cost = project_per_role_cost(role, assumption, pricing, overlay)
        by_role[role] = cost
        per_run = per_run + cost
    total = per_run * Decimal(overlay.n_runs)
    return ScaleProjection(
        n_runs=overlay.n_runs,
        infra_monthly_usd=overlay.infra_monthly_usd,
        per_run_usd=per_run,
        total_usd=total,
        architecture_notes=overlay.architecture_notes,
        by_role_usd=by_role,
    )


def actual_dev_spend_from_session(
    session: Session,
) -> tuple[Decimal, dict[str, Decimal], bool]:
    """Aggregate `cost_ledger.cost_usd` grouped by `agent_role`.

    Returns (total, by_role, was_measured). ``was_measured`` is True if any
    rows exist (even if their sums are zero — the Red Team's :free tier
    contributes rows with $0).
    """
    try:
        stmt = select(
            CostLedgerEntry.agent_role,
            func.coalesce(func.sum(CostLedgerEntry.cost_usd), 0),
        ).group_by(CostLedgerEntry.agent_role)
        rows = session.execute(stmt).all()
    except Exception:
        return Decimal("0"), {}, False

    by_role: dict[str, Decimal] = {}
    total = Decimal("0")
    for role, sum_val in rows:
        amt = sum_val if isinstance(sum_val, Decimal) else Decimal(str(sum_val))
        by_role[str(role)] = amt
        total = total + amt
    return total, by_role, len(rows) > 0


def actual_dev_spend(db_url: str | None) -> tuple[Decimal, dict[str, Decimal], bool]:
    """Back-compat wrapper for `scripts/cost_extrapolate.py` — opens its own
    short-lived engine instead of taking a session.

    The FastAPI path uses ``actual_dev_spend_from_session`` with the route's
    DI-supplied session; offline script invocations still go through here.
    """
    if not db_url:
        return Decimal("0"), {}, False
    try:
        from agentforge.memory.db import make_engine, make_session_factory
    except Exception:
        return Decimal("0"), {}, False

    try:
        engine = make_engine(db_url)
        factory = make_session_factory(engine)
        session = factory()
    except Exception:
        return Decimal("0"), {}, False
    try:
        return actual_dev_spend_from_session(session)
    finally:
        with contextlib.suppress(Exception):
            session.close()


def serialize_payload(
    *,
    pricing: PricingTable,
    projections: list[ScaleProjection],
    actual_spend_total: Decimal,
    actual_spend_by_role: dict[str, Decimal],
    measured: bool,
    assumptions: dict[str, RoleAssumption],
) -> dict[str, Any]:
    """Build the JSON-serializable payload (Decimal → str)."""

    def _d(value: Decimal, places: str = "0.000001") -> str:
        return str(_quantize(value, places))

    scales_out: list[dict[str, Any]] = []
    for p in projections:
        scales_out.append(
            {
                "n_runs": p.n_runs,
                "infra_monthly_usd": _d(p.infra_monthly_usd, "0.01"),
                "per_run_usd": _d(p.per_run_usd),
                "total_usd": _d(p.total_usd, "0.01"),
                "architecture_notes": p.architecture_notes,
                "by_role_usd": {role: _d(cost) for role, cost in p.by_role_usd.items()},
            }
        )

    actual_spend_display = _d(actual_spend_total, "0.01") if measured else "0.00 (modelled)"

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "pricing_retrieved_on": pricing.retrieved_on.isoformat(),
        "redteam_provider": "openrouter",
        "scales": scales_out,
        "assumptions": {
            role: {
                "provider": a.provider,
                "model": a.model,
                "input_tokens": a.input_tokens,
                "output_tokens": a.output_tokens,
                "calls_per_run": str(a.calls_per_run),
            }
            for role, a in assumptions.items()
        },
        "actual_dev_spend_usd": actual_spend_display,
        "actual_dev_spend_by_role_usd": {
            role: _d(amt, "0.01") for role, amt in actual_spend_by_role.items()
        },
    }


def build_projections_payload(
    session: Session,
    pricing_path: Path | None = None,
) -> dict[str, Any]:
    """The single entry point the FastAPI route calls.

    Loads pricing from `config/pricing.yml` (override via `pricing_path` for
    tests), builds all four scale projections, overlays measured spend from
    the given session's `cost_ledger`, returns the JSON-shaped payload that
    matches ``CostProjectionsResponse``.
    """
    pricing = PricingTable.from_yaml(pricing_path or DEFAULT_PRICING_PATH)
    projections = [
        build_scale_projection(pricing, DEFAULT_ASSUMPTIONS, overlay) for overlay in SCALE_OVERLAYS
    ]
    actual_total, actual_by_role, measured = actual_dev_spend_from_session(session)
    return serialize_payload(
        pricing=pricing,
        projections=projections,
        actual_spend_total=actual_total,
        actual_spend_by_role=actual_by_role,
        measured=measured,
        assumptions=DEFAULT_ASSUMPTIONS,
    )
