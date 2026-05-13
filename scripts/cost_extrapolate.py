"""Cost extrapolation script — PRD hard-gate deliverable (master plan §15).

Models projected production cost of running the AgentForge adversarial
platform at four scales (100 / 1K / 10K / 100K test runs). Combines a
per-call cost model (per agent role) with an architectural-change overlay at
each scale, because cost-at-scale is not simply cost-per-token * n_runs.

Inputs:
    - ``config/pricing.yml`` via ``PricingTable.from_yaml`` — every USD price
      flows through this table; no prices are hardcoded here.
    - ``cost_ledger`` table (when ``--db-url`` points at a populated DB) —
      provides actual dev spend grouped by ``agent_role``. Empty DB falls
      back to a "modelled, not measured" report.

Outputs:
    - JSON written to ``evals/results/cost_extrapolate_<ISO8601>.json``.
    - Markdown summary table printed to stdout.

Decimal arithmetic everywhere. No live LLM calls.

CLI:
    python scripts/cost_extrapolate.py --help
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

# Make `agentforge` importable when this script is invoked directly via
# ``python scripts/cost_extrapolate.py`` (i.e. when the package is not yet
# installed in development mode). When run via ``poetry run`` or after
# ``pip install -e .``, this is a harmless no-op.
_REPO_ROOT_FOR_IMPORT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORT))

from agentforge.pricing import PricingTable  # noqa: E402 — path bootstrap above

# ---------------------------------------------------------------------------
# Repo root resolution. The script lives at scripts/cost_extrapolate.py and
# is expected to be invoked from the repo root, but we resolve relative paths
# anchored to this file so it works regardless of cwd.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRICING = REPO_ROOT / "config" / "pricing.yml"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "evals" / "results"


# ---------------------------------------------------------------------------
# Per-role assumption model. These are deliberately exposed as constants so
# tests can read them and CLI flags can override them.
#
# token counts are per call; calls_per_run is the expected number of calls of
# that role per platform test run (e.g. the External Judge runs ~5 rubrics
# per attack and so contributes 5 calls).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoleAssumption:
    """Per-role token + call-count assumption used to model cost.

    All fields are stored as primitives; arithmetic on the cost path uses
    ``Decimal`` end-to-end via ``PricingTable.cost_for_call``.
    """

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
        # One planner call per batch of 10 attacks → 0.1 calls per attack.
        calls_per_run=Decimal("0.1"),
    ),
    "red_team": RoleAssumption(
        provider="openrouter",
        model="cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
        input_tokens=800,
        output_tokens=400,
        # One paraphrase per attack. $0 on the :free tier.
        calls_per_run=Decimal("1"),
    ),
    "internal_judge": RoleAssumption(
        provider="anthropic",
        model="claude-haiku-4-6",
        input_tokens=1000,
        output_tokens=100,
        # Most rubrics deterministic; Haiku only fires on ambiguous cases.
        calls_per_run=Decimal("0.3"),
    ),
    "external_judge": RoleAssumption(
        provider="anthropic",
        model="claude-sonnet-4-6",
        input_tokens=1500,
        output_tokens=200,
        # One call per non-deterministic rubric, ~5 per attack at <100K scale.
        # At 100K scale the script switches to a batched form (see overlay).
        calls_per_run=Decimal("5"),
    ),
    "documentation": RoleAssumption(
        provider="anthropic",
        model="claude-sonnet-4-6",
        input_tokens=2000,
        output_tokens=600,
        # Only confirmed exploits get a write; ~10% of attacks.
        calls_per_run=Decimal("0.1"),
    ),
}


# ---------------------------------------------------------------------------
# Per-scale architectural-change overlay. PRD verbatim: "This is not simply
# cost-per-token * n runs." Each scale carries a fixed-cost infra footprint
# and a per-call overhead multiplier reflecting the queueing / batching cost
# of running at that throughput.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScaleOverlay:
    """Architectural-change overlay applied at a given run-count scale.

    ``per_call_overhead`` is a multiplier on the per-call cost (1.05 means
    +5%). ``external_judge_batching_factor`` is a multiplier on the
    External Judge's calls_per_run (0.2 = 5 rubrics collapsed into 1 call).
    """

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
        # 5 rubrics collapsed to 1 batched call → 0.20 factor on calls_per_run,
        # which is a 30% real cost reduction once input-token amortization is
        # accounted for (batched prompt is shared across rubrics).
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
# Core projection
# ---------------------------------------------------------------------------


@dataclass
class ScaleProjection:
    """Output row for a single scale."""

    n_runs: int
    infra_monthly_usd: Decimal
    per_run_usd: Decimal
    total_usd: Decimal
    architecture_notes: str
    by_role_usd: dict[str, Decimal] = field(default_factory=dict)


def _quantize(value: Decimal, places: str = "0.000001") -> Decimal:
    """Quantize a Decimal to a fixed places string. Keeps Decimal type."""
    return value.quantize(Decimal(places))


def project_per_role_cost(
    role: str,
    assumption: RoleAssumption,
    pricing: PricingTable,
    overlay: ScaleOverlay,
) -> Decimal:
    """USD cost contributed by one role for ONE platform test run.

    Applies per-call overhead (queueing/batching tax) and, for the External
    Judge at the highest scale, the batching factor on calls_per_run.

    Returns a ``Decimal`` (never float).
    """
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
    """Compute the per-role + per-run + total cost for one scale."""
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


# ---------------------------------------------------------------------------
# Cost-ledger rollup
# ---------------------------------------------------------------------------


def actual_dev_spend(db_url: str | None) -> tuple[Decimal, dict[str, Decimal], bool]:
    """Return (total_spend, by_role_spend, was_measured).

    If the DB cannot be reached or is empty, returns (Decimal('0'), {}, False)
    so callers can mark the projection as "modelled, not measured".
    """
    if not db_url:
        return Decimal("0"), {}, False
    try:
        from sqlalchemy import func, select  # local import — avoid global cost

        from agentforge.memory.db import make_engine, make_session_factory
        from agentforge.memory.models import CostLedgerEntry
    except Exception:
        return Decimal("0"), {}, False

    try:
        engine = make_engine(db_url)
        factory = make_session_factory(engine)
        session = factory()
    except Exception:
        return Decimal("0"), {}, False
    try:
        stmt = select(
            CostLedgerEntry.agent_role,
            func.coalesce(func.sum(CostLedgerEntry.cost_usd), 0),
        ).group_by(CostLedgerEntry.agent_role)
        rows = session.execute(stmt).all()
    except Exception:
        session.close()
        return Decimal("0"), {}, False
    finally:
        with contextlib.suppress(Exception):
            session.close()

    by_role: dict[str, Decimal] = {}
    total = Decimal("0")
    for role, sum_val in rows:
        amt = sum_val if isinstance(sum_val, Decimal) else Decimal(str(sum_val))
        by_role[str(role)] = amt
        total = total + amt
    measured = total > 0 or len(rows) > 0
    return total, by_role, measured


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_markdown_table(projections: list[ScaleProjection]) -> str:
    """Stdout-friendly Markdown table with the four-scale projection."""
    lines: list[str] = []
    lines.append("| n_runs | per_run_usd | total_usd | infra_monthly_usd | external_judge_share |")
    lines.append("| ---: | ---: | ---: | ---: | ---: |")
    for p in projections:
        ej = p.by_role_usd.get("external_judge", Decimal("0"))
        share = (ej / p.per_run_usd) if p.per_run_usd > 0 else Decimal("0")
        lines.append(
            f"| {p.n_runs:>6d} "
            f"| ${_quantize(p.per_run_usd, '0.000001')} "
            f"| ${_quantize(p.total_usd, '0.01')} "
            f"| ${_quantize(p.infra_monthly_usd, '0.01')} "
            f"| {(share * 100).quantize(Decimal('0.01'))}% |"
        )
    return "\n".join(lines)


def serialize_payload(
    *,
    pricing: PricingTable,
    projections: list[ScaleProjection],
    actual_spend_total: Decimal,
    actual_spend_by_role: dict[str, Decimal],
    measured: bool,
    assumptions: dict[str, RoleAssumption],
) -> dict[str, Any]:
    """Build the JSON-serializable payload (Decimal → str for safety)."""

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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Project AgentForge adversarial-platform cost at 100/1K/10K/100K "
            "test runs, with architectural-change overlay per PRD §15."
        )
    )
    parser.add_argument(
        "--pricing",
        default=str(DEFAULT_PRICING),
        help="Path to pricing yaml (default: config/pricing.yml).",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help=(
            "Platform DB URL (e.g. sqlite:///./data/agentforge.sqlite). "
            "If omitted or unreachable, actual dev spend is reported as "
            "'modelled, not measured'."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help=("Output JSON path. Default: " "evals/results/cost_extrapolate_<ISO8601>.json."),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    pricing_path = Path(args.pricing)
    pricing = PricingTable.from_yaml(pricing_path)

    projections = [
        build_scale_projection(pricing, DEFAULT_ASSUMPTIONS, overlay) for overlay in SCALE_OVERLAYS
    ]

    actual_total, actual_by_role, measured = actual_dev_spend(args.db_url)

    payload = serialize_payload(
        pricing=pricing,
        projections=projections,
        actual_spend_total=actual_total,
        actual_spend_by_role=actual_by_role,
        measured=measured,
        assumptions=DEFAULT_ASSUMPTIONS,
    )

    if args.output:
        out_path = Path(args.output)
    else:
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_path = DEFAULT_OUTPUT_DIR / f"cost_extrapolate_{stamp}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(
        "AgentForge cost extrapolation — modelled, not measured"
        if not measured
        else "AgentForge cost extrapolation — actual spend overlaid where available"
    )
    print(f"pricing retrieved_on: {pricing.retrieved_on.isoformat()}")
    print(f"output: {out_path}")
    print()
    print(render_markdown_table(projections))
    print()
    print(f"actual_dev_spend_usd: {payload['actual_dev_spend_usd']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
