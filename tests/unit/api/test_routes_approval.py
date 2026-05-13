"""Tests for /v1/approval — master plan §4."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.mark.unit
def test_approval_queue_lists_jsonl(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qpath = tmp_path / "notifier_queue.jsonl"
    items = [
        {"vr_id": "VR-1", "kind": "budget_raise"},
        {"vr_id": "VR-2", "kind": "new_target"},
    ]
    qpath.write_text("\n".join(json.dumps(i) for i in items), encoding="utf-8")

    import agentforge.api.routes_approval as mod

    monkeypatch.setattr(mod, "_QUEUE_PATH", qpath)
    monkeypatch.setattr(mod, "_queue_path", lambda: qpath)

    r = client.get("/v1/approval/queue")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2
    assert body["items"][0]["vr_id"] == "VR-1"


@pytest.mark.unit
def test_approval_approve_returns_501(client: TestClient) -> None:
    r = client.post("/v1/approval/VR-1/approve")
    assert r.status_code == 501


@pytest.mark.unit
def test_approval_reject_returns_501(client: TestClient) -> None:
    r = client.post("/v1/approval/VR-1/reject")
    assert r.status_code == 501
