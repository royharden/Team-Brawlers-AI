"""Tests for /v1/cost — master plan §4 / §15."""

from __future__ import annotations

import json
from pathlib import Path

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
def test_cost_projections_reads_latest_file(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`/v1/cost/projections` reads the most-recent `evals/results/cost_extrapolate_*.json`."""
    payload = {
        "generated_at": "2026-01-01T00:00:00Z",
        "pricing_retrieved_on": "2026-01-01",
        "actual_dev_spend_usd": "1.23",
        "scales": [
            {
                "n_runs": 100,
                "per_run_usd": "0.012345",
                "total_usd": "1.23",
                "infra_monthly_usd": "0.00",
                "architecture_notes": "fixture",
                "by_role_usd": {"red_team": "0.0"},
            }
        ],
    }
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    fpath = results_dir / "cost_extrapolate_20260101T000000Z.json"
    fpath.write_text(json.dumps(payload), encoding="utf-8")

    # Patch the resolved dir the route reads from.
    import agentforge.api.routes_cost as mod

    monkeypatch.setattr(mod, "_COST_RESULTS_DIR", results_dir)

    r = client.get("/v1/cost/projections")
    assert r.status_code == 200
    body = r.json()
    assert body["actual_dev_spend_usd"] == "1.23"
    assert body["scales"][0]["n_runs"] == 100
    assert body["scales"][0]["architecture_notes"] == "fixture"
