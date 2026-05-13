"""/v1/targets/{id}/defense-delta routes — master plan §4."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/targets/{target_id}/defense-delta")
def get_defense_delta(target_id: str) -> dict[str, str]:
    """Defense Delta Score series. Phase 4 wires this up."""
    raise HTTPException(status_code=501, detail="Phase 4 — not yet wired")
