"""/v1/approval routes — human-in-the-loop queue (master plan §4)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from agentforge.api.responses import ApprovalQueueItem, ApprovalQueueResponse

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parents[2]
_QUEUE_PATH = _REPO_ROOT / "data" / "notifier_queue.jsonl"


def _queue_path() -> Path:
    """Indirection so tests can monkeypatch."""
    return _QUEUE_PATH


@router.get("/approval/queue", response_model=ApprovalQueueResponse)
def list_approval_queue() -> ApprovalQueueResponse:
    """Read the notifier queue JSONL into a list of items."""
    path = _queue_path()
    items: list[ApprovalQueueItem] = []
    if not path.exists():
        return ApprovalQueueResponse(items=[])
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ApprovalQueueResponse(items=[])
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        items.append(
            ApprovalQueueItem(
                vr_id=obj.get("vr_id"),
                kind=obj.get("kind"),
                payload=obj,
            )
        )
    return ApprovalQueueResponse(items=items)


@router.post("/approval/{vr_id}/approve", status_code=501)
def approve(vr_id: str) -> dict[str, str]:
    """Approve a queued item. Phase 8 wiring."""
    raise HTTPException(
        status_code=501, detail=f"Phase 8 wiring — approve for {vr_id}"
    )


@router.post("/approval/{vr_id}/reject", status_code=501)
def reject(vr_id: str) -> dict[str, str]:
    """Reject a queued item. Phase 8 wiring."""
    raise HTTPException(
        status_code=501, detail=f"Phase 8 wiring — reject for {vr_id}"
    )
