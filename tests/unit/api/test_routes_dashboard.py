"""Tests for /v1/dashboard + /healthz — master plan §4."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.unit.api.conftest import (
    seed_coverage,
    seed_cost,
    seed_run,
    seed_vuln_report,
)


@pytest.mark.unit
def test_healthz_ok(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["phase"] == "5"
    assert body["tests_passing"] >= 1
    assert "version" in body


@pytest.mark.unit
def test_dashboard_empty(client: TestClient) -> None:
    r = client.get("/v1/dashboard")
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["runs"] == 0
    assert body["totals"]["attacks"] == 0
    assert body["coverage_summary"]["total_cells"] == 72
    assert body["coverage_summary"]["covered_cells"] == 0
    assert body["latest_run"] is None


@pytest.mark.unit
def test_dashboard_with_seeded_data(client: TestClient, seeded_session) -> None:
    seed_run(seeded_session, "run-a", status="done")
    seed_vuln_report(seeded_session, vr_id="VR-100", severity="high")
    seed_cost(seeded_session, role="red_team", amount="0.50")
    seed_coverage(seeded_session, "prompt_injection", "single_turn", attempts=5)
    seeded_session.commit()

    r = client.get("/v1/dashboard")
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["runs"] == 1
    assert body["totals"]["vrs_open"] == 1
    assert body["coverage_summary"]["covered_cells"] == 1
    assert body["latest_run"]["id"] == "run-a"
    # spend should reflect the 0.50 we inserted (Decimal repr).
    assert "0.5" in body["totals"]["spend_usd"]
