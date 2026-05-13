"""Tests for /v1/runs — master plan §4."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.unit.api.conftest import (
    seed_attack,
    seed_run,
    seed_verdict,
)


@pytest.mark.unit
def test_runs_list_pagination(client: TestClient, seeded_session) -> None:
    """`/v1/runs?limit&offset` returns the requested slice + total."""
    for i in range(5):
        seed_run(seeded_session, run_id=f"run-{i}")
    seeded_session.commit()

    r = client.get("/v1/runs", params={"limit": 2, "offset": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert len(body["runs"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 1


@pytest.mark.unit
def test_run_detail_counts_attacks_and_verdicts(client: TestClient, seeded_session) -> None:
    """`/v1/runs/{id}` joins through `attack_traces` to count verdicts."""
    seed_run(seeded_session, "run-x")
    seed_attack(
        seeded_session,
        run_id="run-x",
        job_id="job-x",
        trace_id="trace-x",
    )
    seed_verdict(seeded_session, trace_id="trace-x", verdict_id="ver-x")
    seeded_session.commit()

    r = client.get("/v1/runs/run-x")
    assert r.status_code == 200
    body = r.json()
    assert body["run"]["id"] == "run-x"
    assert body["attack_count"] == 1
    assert body["verdict_count"] == 1


@pytest.mark.unit
def test_run_detail_404(client: TestClient) -> None:
    """Unknown run id returns 404 (no silent zero-row body)."""
    r = client.get("/v1/runs/nonexistent")
    assert r.status_code == 404


@pytest.mark.unit
def test_runs_start_returns_501_phase_8(client: TestClient) -> None:
    """Mutating `POST /v1/runs/start` is a Phase-8 stub returning 501 (read-only surface in Phase 5)."""
    r = client.post("/v1/runs/start")
    assert r.status_code == 501
