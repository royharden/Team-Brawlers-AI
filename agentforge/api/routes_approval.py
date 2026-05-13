"""/v1/approvals routes — human gate for budget raise / new target (master plan §4)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/approvals")
def post_approval() -> dict[str, str]:
    """Submit a human approval. Phase 4 wires this up."""
    raise HTTPException(status_code=501, detail="Phase 4 — not yet wired")
