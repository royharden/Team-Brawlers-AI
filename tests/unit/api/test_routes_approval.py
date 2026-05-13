"""Tests for /v1/approval — master plan §4 + sub-plan Next04 (POST wiring)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _seed_queue(qpath: Path, items: list[dict]) -> None:
    qpath.write_text("\n".join(json.dumps(i, sort_keys=True) for i in items), encoding="utf-8")


def _patch_queue_path(monkeypatch: pytest.MonkeyPatch, qpath: Path) -> None:
    import agentforge.api.routes_approval as mod

    monkeypatch.setattr(mod, "_QUEUE_PATH", qpath)
    monkeypatch.setattr(mod, "_queue_path", lambda: qpath)


@pytest.mark.unit
def test_approval_queue_lists_jsonl(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`/v1/approval/queue` reads `data/notifier_queue.jsonl` line-by-line."""
    qpath = tmp_path / "notifier_queue.jsonl"
    _seed_queue(
        qpath,
        [
            {"vr_id": "VR-1", "kind": "budget_raise"},
            {"vr_id": "VR-2", "kind": "new_target"},
        ],
    )
    _patch_queue_path(monkeypatch, qpath)

    r = client.get("/v1/approval/queue")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2
    assert body["items"][0]["vr_id"] == "VR-1"


# --- sub-plan Next04: Approve / Reject / Dismiss POST wiring -----------------


@pytest.mark.unit
def test_approval_approve_stamps_review_block(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`POST /v1/approval/{vr_id}/approve` adds a review block on the queue
    line and rewrites the JSONL file in place (sub-plan Next04)."""
    qpath = tmp_path / "notifier_queue.jsonl"
    _seed_queue(qpath, [{"vr_id": "VR-1", "kind": "high"}, {"vr_id": "VR-2", "kind": "medium"}])
    _patch_queue_path(monkeypatch, qpath)

    r = client.post("/v1/approval/VR-1/approve", params={"reviewer": "alice"})
    assert r.status_code == 200
    body = r.json()
    assert body["vr_id"] == "VR-1"
    assert body["item"]["review"]["status"] == "approved"
    assert body["item"]["review"]["reviewer"] == "alice"
    assert "reviewed_at" in body["item"]["review"]

    # File was rewritten with the new review block.
    on_disk = [json.loads(line) for line in qpath.read_text(encoding="utf-8").splitlines() if line]
    assert len(on_disk) == 2
    by_id = {i["vr_id"]: i for i in on_disk}
    assert by_id["VR-1"]["review"]["status"] == "approved"
    # VR-2 untouched.
    assert "review" not in by_id["VR-2"]


@pytest.mark.unit
def test_approval_reject_stamps_review_block(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`POST /v1/approval/{vr_id}/reject` writes status=rejected (sub-plan Next04)."""
    qpath = tmp_path / "notifier_queue.jsonl"
    _seed_queue(qpath, [{"vr_id": "VR-9", "kind": "critical"}])
    _patch_queue_path(monkeypatch, qpath)

    r = client.post("/v1/approval/VR-9/reject")
    assert r.status_code == 200
    assert r.json()["item"]["review"]["status"] == "rejected"
    on_disk = [json.loads(line) for line in qpath.read_text(encoding="utf-8").splitlines() if line]
    assert on_disk[0]["review"]["status"] == "rejected"


@pytest.mark.unit
def test_approval_dismiss_stamps_review_block(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`POST /v1/approval/{vr_id}/dismiss` writes status=dismissed (sub-plan Next04)."""
    qpath = tmp_path / "notifier_queue.jsonl"
    _seed_queue(qpath, [{"vr_id": "VR-5", "kind": "high"}])
    _patch_queue_path(monkeypatch, qpath)

    r = client.post("/v1/approval/VR-5/dismiss")
    assert r.status_code == 200
    assert r.json()["item"]["review"]["status"] == "dismissed"


@pytest.mark.unit
def test_approval_overwrites_existing_review(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second approve overwrites a prior review block — useful for
    correcting a mistaken reject (sub-plan Next04)."""
    qpath = tmp_path / "notifier_queue.jsonl"
    _seed_queue(
        qpath,
        [
            {
                "vr_id": "VR-7",
                "kind": "high",
                "review": {
                    "status": "rejected",
                    "reviewer": "bob",
                    "reviewed_at": "2026-05-15T00:00:00+00:00",
                },
            }
        ],
    )
    _patch_queue_path(monkeypatch, qpath)

    r = client.post("/v1/approval/VR-7/approve")
    assert r.status_code == 200
    assert r.json()["item"]["review"]["status"] == "approved"
    assert r.json()["item"]["review"]["reviewer"] == "operator"


@pytest.mark.unit
def test_approval_404_for_unknown_vr_id(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A POST against a vr_id that's not in the queue returns 404 — protects
    against typo'd ids stamping bogus reviews (sub-plan Next04)."""
    qpath = tmp_path / "notifier_queue.jsonl"
    _seed_queue(qpath, [{"vr_id": "VR-1", "kind": "high"}])
    _patch_queue_path(monkeypatch, qpath)

    r = client.post("/v1/approval/VR-DOES-NOT-EXIST/approve")
    assert r.status_code == 404
