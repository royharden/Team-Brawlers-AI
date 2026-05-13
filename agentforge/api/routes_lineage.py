"""/v1/runs/{id}/lineage routes — Attack Lineage Map (master plan §4)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/runs/{run_id}/lineage")
def get_lineage(run_id: str) -> dict[str, str]:
    """Attack lineage graph. Phase 2 wires this up."""
    raise HTTPException(status_code=501, detail="Phase 2 — not yet wired")
