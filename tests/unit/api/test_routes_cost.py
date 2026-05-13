"""Tests for /v1/cost — master plan §4 / §15.

Sub-plan Next03 §3.3: `/v1/cost/projections` no longer reads from a JSON
file in ``evals/results/`` — it computes in-process from
``config/pricing.yml`` + the session's ``cost_ledger`` table. The
file-based behavior previously asserted by
``test_cost_projections_reads_latest_file`` is gone; this file pins the
new contract.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from tests.unit.api.conftest import seed_cost


@pytest.mark.unit
def test_cost_today_aggregates_ledger(client: TestClient, seeded_session) -> None:
    """`/v1/cost/today` rolls cost_ledger up by `agent_role` and counts calls."""
    seed_cost(seeded_session, role="red_team", amount="0.10")
    seed_cost(seeded_session, role="red_team", amount="0.20")
    seed_cost(seeded_session, role="external_judge", amount="1.00")
    seeded_session.commit()

    r = client.get("/v1/cost/today")
    assert r.status_code == 200
    body = r.json()
    assert body["n_calls"] == 3
    # by_role aggregates Decimal sums; comparable as string.
    assert "0.3" in body["by_role"]["red_team"]
    assert "1" in body["by_role"]["external_judge"]


@pytest.mark.unit
def test_cost_projections_computed_from_pricing_yml_with_empty_ledger(
    client: TestClient,
) -> None:
    """`/v1/cost/projections` returns the four-scale projection with non-zero
    `per_run_usd` even when the cost_ledger is empty — pricing.yml + the
    `DEFAULT_ASSUMPTIONS` model are sufficient input (sub-plan Next03 §3.3).
    """
    r = client.get("/v1/cost/projections")
    assert r.status_code == 200
    body = r.json()
    assert body["pricing_retrieved_on"] == "2026-05-13"
    assert {s["n_runs"] for s in body["scales"]} == {100, 1000, 10000, 100000}
    # Every scale has a non-zero per-run cost (the External Judge dominates).
    for s in body["scales"]:
        assert Decimal(s["per_run_usd"]) > Decimal("0")
    # No ledger rows → spend is reported as "0.00 (modelled)".
    assert "modelled" in body["actual_dev_spend_usd"]


@pytest.mark.unit
def test_cost_projections_reflects_recent_ledger_spend(client: TestClient, seeded_session) -> None:
    """Seeded `cost_ledger` rows flow into `actual_dev_spend_usd` on the projections
    payload (sub-plan Next03 §3.3)."""
    seed_cost(seeded_session, role="orchestrator", amount="0.40")
    seed_cost(seeded_session, role="external_judge", amount="2.10")
    seed_cost(seeded_session, role="external_judge", amount="0.05")
    seeded_session.commit()

    r = client.get("/v1/cost/projections")
    assert r.status_code == 200
    body = r.json()
    # Sum: 0.40 + 2.10 + 0.05 = 2.55. The serializer quantizes to "0.01" places.
    assert body["actual_dev_spend_usd"] == "2.55"
