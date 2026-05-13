"""/v1/approval routes — human-in-the-loop queue (master plan §4).

Sub-plan Next04 wired the Approve / Reject POST endpoints. Each POST adds
(or overwrites) a ``review`` block on the matching queue line:

    {"vr_id": "VR-0001", "kind": "high", ...,
     "review": {"status": "approved", "reviewer": "operator",
                "reviewed_at": "2026-05-15T..."}}

The whole queue file is rewritten atomically (temp file + os.replace) so a
crash mid-write never leaves a partial line. The GET endpoint surfaces
the review block on each item so the UI can dim / hide already-reviewed
findings.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from agentforge.api.responses import ApprovalQueueItem, ApprovalQueueResponse

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parents[2]
_QUEUE_PATH = _REPO_ROOT / "data" / "notifier_queue.jsonl"

_VALID_STATUSES = {"approved", "rejected", "dismissed"}


def _queue_path() -> Path:
    """Indirection so tests can monkeypatch."""
    return _QUEUE_PATH


def _read_queue(path: Path) -> list[dict[str, Any]]:
    """Read the JSONL queue into a list of dicts. Skips malformed lines."""
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _atomic_write_queue(path: Path, items: list[dict[str, Any]]) -> None:
    """Rewrite the queue JSONL atomically (temp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for item in items:
                fh.write(json.dumps(item, sort_keys=True))
                fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _set_review(vr_id: str, status: str, reviewer: str) -> dict[str, Any]:
    """Find the queue line for ``vr_id`` and stamp / update its ``review`` block.

    Raises HTTPException(404) if no matching line exists. Returns the
    updated item dict.
    """
    if status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {sorted(_VALID_STATUSES)}; got {status!r}",
        )
    items = _read_queue(_queue_path())
    target: dict[str, Any] | None = None
    for item in items:
        if item.get("vr_id") == vr_id:
            target = item
            break
    if target is None:
        raise HTTPException(status_code=404, detail=f"vr_id not in approval queue: {vr_id}")
    target["review"] = {
        "status": status,
        "reviewer": reviewer,
        "reviewed_at": datetime.now(UTC).isoformat(),
    }
    _atomic_write_queue(_queue_path(), items)
    return target


@router.get("/approval/queue", response_model=ApprovalQueueResponse)
def list_approval_queue() -> ApprovalQueueResponse:
    """Read the notifier queue JSONL into a list of items."""
    items = _read_queue(_queue_path())
    return ApprovalQueueResponse(
        items=[
            ApprovalQueueItem(
                vr_id=obj.get("vr_id"),
                kind=obj.get("kind"),
                payload=obj,
            )
            for obj in items
        ]
    )


@router.post("/approval/{vr_id}/approve")
def approve(
    vr_id: str,
    reviewer: str = Query(default="operator", description="Reviewer identity for the audit trail."),
) -> dict[str, Any]:
    """Stamp an `approved` review on the queue line for ``vr_id``."""
    return {"vr_id": vr_id, "item": _set_review(vr_id, "approved", reviewer)}


@router.post("/approval/{vr_id}/reject")
def reject(
    vr_id: str,
    reviewer: str = Query(default="operator", description="Reviewer identity for the audit trail."),
) -> dict[str, Any]:
    """Stamp a `rejected` review on the queue line for ``vr_id``."""
    return {"vr_id": vr_id, "item": _set_review(vr_id, "rejected", reviewer)}


@router.post("/approval/{vr_id}/dismiss")
def dismiss(
    vr_id: str,
    reviewer: str = Query(default="operator", description="Reviewer identity for the audit trail."),
) -> dict[str, Any]:
    """Stamp a `dismissed` review on the queue line for ``vr_id``."""
    return {"vr_id": vr_id, "item": _set_review(vr_id, "dismissed", reviewer)}
