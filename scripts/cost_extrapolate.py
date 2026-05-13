"""Cost extrapolation script — PRD hard-gate deliverable (master plan §15).

Models projected production cost of running the AgentForge adversarial
platform at four scales (100 / 1K / 10K / 100K test runs).

Sub-plan Next03 §3.3 moved the projection model itself into
:mod:`agentforge.cost.projections` so the FastAPI ``/v1/cost/projections``
route can compute fresh projections per-request without depending on the
JSON artifact this script writes. The script is preserved for the
PRD-deliverable on-disk record (``evals/results/cost_extrapolate_*.json``)
and for offline runs that don't require a running API process.

Inputs:
    - ``config/pricing.yml`` via ``PricingTable.from_yaml``.
    - ``cost_ledger`` table (when ``--db-url`` is supplied).

Outputs:
    - JSON written to ``evals/results/cost_extrapolate_<ISO8601>.json``.
    - Markdown summary table printed to stdout.

CLI:
    python scripts/cost_extrapolate.py --help
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

_REPO_ROOT_FOR_IMPORT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORT))

from agentforge.cost.projections import (  # noqa: E402
    DEFAULT_ASSUMPTIONS,
    DEFAULT_PRICING_PATH,
    SCALE_OVERLAYS,
    ScaleProjection,
    actual_dev_spend,
    build_scale_projection,
    serialize_payload,
)
from agentforge.pricing import PricingTable  # noqa: E402

REPO_ROOT = _REPO_ROOT_FOR_IMPORT
DEFAULT_PRICING = DEFAULT_PRICING_PATH
DEFAULT_OUTPUT_DIR = REPO_ROOT / "evals" / "results"


def _quantize(value: Decimal, places: str = "0.000001") -> Decimal:
    return value.quantize(Decimal(places))


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
        help=("Output JSON path. Default: evals/results/cost_extrapolate_<ISO8601>.json."),
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
