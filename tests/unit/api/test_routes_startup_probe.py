"""Tests for /v1/startup-probe — Next06 §1."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentforge.llm.startup_probe import ProbeResult


def _stub_results() -> list[ProbeResult]:
    return [
        ProbeResult(
            provider="anthropic",
            role="internal_judge",
            model="claude-haiku-4-5",
            status="ok",
            latency_ms=120,
        ),
        ProbeResult(
            provider="anthropic",
            role="orchestrator_planner",
            model="claude-sonnet-4-6",
            status="error",
            error="404 not_found: model claude-sonnet-4-6",
            latency_ms=44,
        ),
        ProbeResult(
            provider="openai",
            role="red_team_openai_fallback",
            model="gpt-4o-mini",
            status="missing_key",
        ),
    ]


@pytest.mark.unit
def test_startup_probe_endpoint_returns_rows_and_counts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Endpoint shape: rows[] + n_ok + n_error + n_missing_key totals."""
    monkeypatch.setattr(
        "agentforge.api.routes_startup_probe.probe_all_configured_models",
        lambda: _stub_results(),
    )
    r = client.get("/v1/startup-probe")
    assert r.status_code == 200
    body = r.json()
    assert len(body["rows"]) == 3
    assert body["n_ok"] == 1
    assert body["n_error"] == 1
    assert body["n_missing_key"] == 1
    err_row = next(row for row in body["rows"] if row["status"] == "error")
    assert err_row["provider"] == "anthropic"
    assert err_row["role"] == "orchestrator_planner"
    assert "404" in err_row["error"]


@pytest.mark.unit
def test_startup_probe_empty_results(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty probe list (defensive — should never happen in practice) →
    zero counts, no crash."""
    monkeypatch.setattr(
        "agentforge.api.routes_startup_probe.probe_all_configured_models",
        lambda: [],
    )
    r = client.get("/v1/startup-probe")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == []
    assert body["n_ok"] == 0
    assert body["n_error"] == 0
    assert body["n_missing_key"] == 0
