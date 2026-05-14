"""Tests for /v1/dashboard + /healthz — master plan §4."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.unit.api.conftest import (
    seed_cost,
    seed_coverage,
    seed_run,
    seed_vuln_report,
)


@pytest.mark.unit
def test_healthz_ok(client: TestClient) -> None:
    """`/healthz` returns `{status:"ok", phase, tests_passing, version}` (master plan §4)."""
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["phase"] == "8"
    assert body["tests_passing"] >= 1
    assert "version" in body


@pytest.mark.unit
def test_dashboard_empty(client: TestClient) -> None:
    """`/v1/dashboard` on an empty DB returns zeros + `total_cells=72` + `latest_run=None` (master plan §4 / §12)."""
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
    """`/v1/dashboard` aggregates seeded runs / VRs / cost / coverage rows."""
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


@pytest.mark.unit
def test_coverage_cells_empty_db(client: TestClient) -> None:
    """`/v1/coverage/cells` on an empty DB returns no rows + total_cells=72 + covered=0
    (sub-plan Next03 §3.1)."""
    r = client.get("/v1/coverage/cells")
    assert r.status_code == 200
    body = r.json()
    assert body["cells"] == []
    assert body["total_cells"] == 72
    assert body["covered_cells"] == 0


@pytest.mark.unit
def test_coverage_cells_returns_seeded_attempts_passes_failures(
    client: TestClient, seeded_session
) -> None:
    """`/v1/coverage/cells` round-trips attempts/passes/failures from coverage_cells
    (sub-plan Next03 §3.1)."""
    seed_coverage(
        seeded_session, "prompt_injection", "single_turn", attempts=5, passes=3, failures=2
    )
    seed_coverage(seeded_session, "tool_misuse", "indirect_pdf", attempts=0, passes=0, failures=0)
    seeded_session.commit()

    r = client.get("/v1/coverage/cells")
    assert r.status_code == 200
    body = r.json()
    cells = body["cells"]
    assert len(cells) == 2
    by_key = {f"{c['category']}/{c['strategy']}": c for c in cells}
    pi = by_key["prompt_injection/single_turn"]
    assert pi["attempts"] == 5
    assert pi["passes"] == 3
    assert pi["failures"] == 2
    assert pi["last_pass_rate"] == pytest.approx(0.6, abs=1e-6)
    tm = by_key["tool_misuse/indirect_pdf"]
    assert tm["attempts"] == 0
    # covered counts only attempts > 0 cells.
    assert body["covered_cells"] == 1


@pytest.mark.unit
def test_coverage_cells_covered_count_matches_dashboard(client: TestClient, seeded_session) -> None:
    """The `covered_cells` field is consistent between `/v1/coverage/cells` and
    `/v1/dashboard.coverage_summary.covered_cells` (sub-plan Next03 §3.1)."""
    seed_coverage(
        seeded_session, "prompt_injection", "single_turn", attempts=2, passes=1, failures=1
    )
    seed_coverage(
        seeded_session, "data_exfiltration", "crescendo", attempts=3, passes=2, failures=1
    )
    seed_coverage(
        seeded_session, "denial_of_service", "tree_of_attacks", attempts=0, passes=0, failures=0
    )
    seeded_session.commit()

    cells_body = client.get("/v1/coverage/cells").json()
    dash_body = client.get("/v1/dashboard").json()
    assert cells_body["covered_cells"] == dash_body["coverage_summary"]["covered_cells"] == 2


@pytest.mark.unit
def test_coverage_cells_pass_rate_round_trip(client: TestClient, seeded_session) -> None:
    """The cell's `last_pass_rate` round-trips as a float (sub-plan Next03 §3.1)."""
    seed_coverage(seeded_session, "identity_role", "role_play", attempts=4, passes=3, failures=1)
    seeded_session.commit()

    body = client.get("/v1/coverage/cells").json()
    assert body["cells"][0]["last_pass_rate"] == pytest.approx(0.75, abs=1e-6)
