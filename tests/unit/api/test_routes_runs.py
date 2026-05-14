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


# --- Next05 §1: live-run streaming endpoints ---------------------------------


@pytest.mark.unit
def test_runs_start_returns_run_id_and_pending_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`POST /v1/runs/start` returns 200 + `{run_id, status}`. The runner
    is monkeypatched so no orchestrator + LLM is actually invoked."""
    from agentforge.api import run_runner

    captured: dict[str, object] = {}

    def _fake_start(run_type: str = "smoke", count: int = 1) -> run_runner.RunState:
        captured["run_type"] = run_type
        captured["count"] = count
        return run_runner.RunState(
            run_id="fake-run-id-1",
            status="pending",
            run_type=run_type,
            count=count,
        )

    monkeypatch.setattr("agentforge.api.routes_runs.start_background_run", _fake_start)

    r = client.post("/v1/runs/start", params={"run_type": "smoke", "count": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == "fake-run-id-1"
    assert body["status"] == "pending"
    assert captured == {"run_type": "smoke", "count": 1}


@pytest.mark.unit
def test_runs_start_429_when_queue_depth_reached(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`POST /v1/runs/start` returns 429 only when the configured queue
    depth (concurrent + queued) is exhausted — Next06 §5."""
    from agentforge.api import run_runner

    def _fake_start(run_type: str = "smoke", count: int = 1) -> run_runner.RunState:
        return run_runner.RunState(
            run_id="",
            status="failed",
            run_type=run_type,
            count=count,
            error="queue depth reached: 5 runs pending/running, max=5",
        )

    monkeypatch.setattr("agentforge.api.routes_runs.start_background_run", _fake_start)

    r = client.post("/v1/runs/start")
    assert r.status_code == 429
    assert "queue depth" in r.json()["detail"]


@pytest.mark.unit
def test_get_run_live_state_404_when_not_tracked(client: TestClient) -> None:
    """`GET /v1/runs/{run_id}/state` returns 404 when the run_id was never
    started or the in-memory tracker has been cleared (server restart)."""
    r = client.get("/v1/runs/nonexistent-rid/state")
    assert r.status_code == 404


@pytest.mark.unit
def test_get_run_live_state_returns_tracked_state(client: TestClient) -> None:
    """`GET /v1/runs/{run_id}/state` returns the runner's in-memory state."""
    from agentforge.api import run_runner

    state = run_runner.RunState(
        run_id="rid-state-test",
        status="running",
        run_type="smoke",
        count=1,
        attacks_executed=2,
    )
    run_runner._set(state)
    try:
        r = client.get("/v1/runs/rid-state-test/state")
        assert r.status_code == 200
        body = r.json()
        assert body["run_id"] == "rid-state-test"
        assert body["status"] == "running"
        assert body["attacks_executed"] == 2
    finally:
        with run_runner._lock:
            run_runner._active_runs.pop("rid-state-test", None)


@pytest.mark.unit
def test_runs_stream_404_when_not_tracked(client: TestClient) -> None:
    """`GET /v1/runs/{run_id}/stream` returns 404 when the run_id is not
    tracked. Doesn't open the SSE stream."""
    r = client.get("/v1/runs/never-existed-rid/stream")
    assert r.status_code == 404
