"""Unit tests for ``scripts/cost_extrapolate.py`` — PRD §15 cost analysis.

These tests pin the cost model so a future agent cannot silently shift the
projected production-cost story without surfacing the change in CI. They
cover (a) pricing-table loading for the OpenRouter Red Team block,
(b) Decimal-arithmetic invariants on the cost path, (c) the architectural-
change overlay at each scale, (d) the cost-ledger rollup path (empty +
seeded), and (e) the JSON output file format.

No live LLM calls; no network.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

# Make scripts/ importable as a module without needing a package init file.
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import cost_extrapolate as cx  # noqa: E402 — path bootstrap above

from agentforge.memory.db import init_db, make_engine, make_session_factory  # noqa: E402
from agentforge.memory.models import CostLedgerEntry, Run  # noqa: E402
from agentforge.pricing import PricingTable  # noqa: E402

PRICING_PATH = REPO_ROOT / "config" / "pricing.yml"


@pytest.fixture
def pricing() -> PricingTable:
    """Load the real config/pricing.yml, pinned at retrieved_on."""
    # `today=retrieved_on` ensures the test never depends on wall-clock drift.
    raw_today = date(2026, 5, 13)
    return PricingTable.from_yaml(PRICING_PATH, today=raw_today, freshness_days=30)


# ---------------------------------------------------------------------------
# Pricing-table sanity for the OpenRouter Red Team block.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pricing_loads_openrouter_block(pricing: PricingTable) -> None:
    """The OpenRouter Dolphin Venice paid variant resolves and costs > 0."""
    paid = "cognitivecomputations/dolphin-mistral-24b-venice-edition"
    free = paid + ":free"
    assert paid in pricing.known_models("openrouter")
    assert free in pricing.known_models("openrouter")
    paid_cost = pricing.cost_for_call("openrouter", paid, 1_000_000, 1_000_000)
    # $0.50 in + $0.50 out per 1M = $1.00 total — exact in Decimal.
    assert paid_cost == Decimal("1.00")


@pytest.mark.unit
def test_dolphin_free_costs_zero(pricing: PricingTable) -> None:
    """The :free OpenRouter variant must yield $0 regardless of token count."""
    free = "cognitivecomputations/dolphin-mistral-24b-venice-edition:free"
    cost = pricing.cost_for_call("openrouter", free, 1_000_000, 1_000_000)
    assert cost == Decimal("0")


# ---------------------------------------------------------------------------
# Per-run cost at the small scale.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_per_run_cost_at_100_scale(pricing: PricingTable) -> None:
    """Modelled per-run cost at the 100-run scale falls in a sensible band ($0.01–$0.50/run) and the Red Team contributes exactly $0."""
    overlay = next(o for o in cx.SCALE_OVERLAYS if o.n_runs == 100)
    projection = cx.build_scale_projection(pricing, cx.DEFAULT_ASSUMPTIONS, overlay)
    # Sensible band. The exact value floats with token assumptions but should
    # never be near zero (we always run the External Judge) and should never
    # exceed $0.50/run at the 100-run scale (no infra overhead, no batching).
    assert Decimal("0.01") < projection.per_run_usd < Decimal("0.50")
    # And the Red Team contributes exactly $0 (Dolphin :free).
    assert projection.by_role_usd["red_team"] == Decimal("0")


# ---------------------------------------------------------------------------
# Cost-share invariants across scales.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_external_judge_dominates_cost_at_10k_scale(pricing: PricingTable) -> None:
    """External Judge is the largest per-role cost line at the 10K-run scale (master plan §15)."""
    overlay = next(o for o in cx.SCALE_OVERLAYS if o.n_runs == 10000)
    projection = cx.build_scale_projection(pricing, cx.DEFAULT_ASSUMPTIONS, overlay)
    by_role = projection.by_role_usd
    ej = by_role["external_judge"]
    # External Judge must be the largest single line item at 10K.
    for role, cost in by_role.items():
        if role == "external_judge":
            continue
        assert cost <= ej, f"{role}={cost} exceeds external_judge={ej}"


@pytest.mark.unit
def test_batching_reduces_external_judge_share_at_100k(pricing: PricingTable) -> None:
    """At 100K scale, External Judge batching shrinks its share of per-run cost."""
    overlay_10k = next(o for o in cx.SCALE_OVERLAYS if o.n_runs == 10000)
    overlay_100k = next(o for o in cx.SCALE_OVERLAYS if o.n_runs == 100000)
    p10 = cx.build_scale_projection(pricing, cx.DEFAULT_ASSUMPTIONS, overlay_10k)
    p100 = cx.build_scale_projection(pricing, cx.DEFAULT_ASSUMPTIONS, overlay_100k)
    share_10 = p10.by_role_usd["external_judge"] / p10.per_run_usd
    share_100 = p100.by_role_usd["external_judge"] / p100.per_run_usd
    assert share_100 < share_10, (
        f"batching should shrink External Judge share: "
        f"10K share={share_10}, 100K share={share_100}"
    )


# ---------------------------------------------------------------------------
# Architectural overlay invariants.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_infra_overlay_added_at_10k_and_100k() -> None:
    """Fixed monthly infra cost is $0 at 100/1K, > $0 at 10K, and strictly higher at 100K — the architectural-change overlay grows with scale."""
    by_scale = {o.n_runs: o for o in cx.SCALE_OVERLAYS}
    assert by_scale[100].infra_monthly_usd == Decimal("0")
    assert by_scale[1000].infra_monthly_usd == Decimal("0")
    assert by_scale[10000].infra_monthly_usd > Decimal("0")
    assert by_scale[100000].infra_monthly_usd > by_scale[10000].infra_monthly_usd


# ---------------------------------------------------------------------------
# Cost-ledger rollup paths.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_actual_dev_spend_from_empty_ledger_is_zero(tmp_path: Path) -> None:
    """An empty cost_ledger table reports (0, {}, measured=False)."""
    db_path = tmp_path / "empty.sqlite"
    db_url = f"sqlite:///{db_path}"
    engine = make_engine(db_url)
    init_db(engine)
    total, by_role, measured = cx.actual_dev_spend(db_url)
    assert total == Decimal("0")
    assert by_role == {}
    assert measured is False


@pytest.mark.unit
def test_actual_dev_spend_with_seed_rows(tmp_path: Path) -> None:
    """Seeded cost_ledger rows roll up into the right per-role + total spend."""
    db_path = tmp_path / "seeded.sqlite"
    db_url = f"sqlite:///{db_path}"
    engine = make_engine(db_url)
    init_db(engine)
    factory = make_session_factory(engine)
    session = factory()
    try:
        run = Run(id="run-cost-1", run_type="smoke", status="completed")
        session.add(run)
        session.commit()
        rows = [
            CostLedgerEntry(
                id=str(uuid.uuid4()),
                run_id="run-cost-1",
                agent_role="orchestrator",
                provider="anthropic",
                model="claude-sonnet-4-6",
                input_tokens=600,
                output_tokens=200,
                cost_usd=Decimal("0.10"),
            ),
            CostLedgerEntry(
                id=str(uuid.uuid4()),
                run_id="run-cost-1",
                agent_role="external_judge",
                provider="anthropic",
                model="claude-sonnet-4-6",
                input_tokens=7500,
                output_tokens=1000,
                cost_usd=Decimal("0.25"),
            ),
            CostLedgerEntry(
                id=str(uuid.uuid4()),
                run_id="run-cost-1",
                agent_role="external_judge",
                provider="anthropic",
                model="claude-sonnet-4-6",
                input_tokens=7500,
                output_tokens=1000,
                cost_usd=Decimal("0.50"),
            ),
        ]
        session.add_all(rows)
        session.commit()
    finally:
        session.close()

    total, by_role, measured = cx.actual_dev_spend(db_url)
    assert measured is True
    assert total == Decimal("0.85")
    assert by_role["orchestrator"] == Decimal("0.10")
    assert by_role["external_judge"] == Decimal("0.75")


# ---------------------------------------------------------------------------
# Output JSON file invariants.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_output_jsonl_written(tmp_path: Path) -> None:
    """End-to-end CLI run writes a JSON file with the expected top-level keys."""
    out = tmp_path / "cost.json"
    rc = cx.main(
        [
            "--pricing",
            str(PRICING_PATH),
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    for key in (
        "generated_at",
        "pricing_retrieved_on",
        "redteam_provider",
        "scales",
        "assumptions",
        "actual_dev_spend_usd",
    ):
        assert key in payload, f"missing top-level key: {key}"
    assert payload["redteam_provider"] == "openrouter"
    assert payload["actual_dev_spend_usd"] == "0.00 (modelled)"
    # Four scales: 100 / 1K / 10K / 100K.
    n_runs_set = {s["n_runs"] for s in payload["scales"]}
    assert n_runs_set == {100, 1000, 10000, 100000}


# ---------------------------------------------------------------------------
# Decimal-arithmetic invariant.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_decimal_arithmetic_no_float_drift(pricing: PricingTable) -> None:
    """Every intermediate in the cost path must be Decimal, not float."""
    overlay = next(o for o in cx.SCALE_OVERLAYS if o.n_runs == 100)
    projection = cx.build_scale_projection(pricing, cx.DEFAULT_ASSUMPTIONS, overlay)
    assert isinstance(projection.per_run_usd, Decimal)
    assert isinstance(projection.total_usd, Decimal)
    assert isinstance(projection.infra_monthly_usd, Decimal)
    for role, cost in projection.by_role_usd.items():
        assert isinstance(cost, Decimal), f"{role} cost is {type(cost).__name__}"

    # Spot-check: 100 runs at exact per-run cost must multiply cleanly.
    expected_total = projection.per_run_usd * Decimal("100")
    assert projection.total_usd == expected_total

    # Also: the Red Team line (Dolphin :free) must be EXACTLY zero, not
    # 0.0000000001 from a float-introduced rounding error.
    assert projection.by_role_usd["red_team"] == Decimal("0")
