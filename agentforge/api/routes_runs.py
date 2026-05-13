"""/v1/runs routes — master plan §4."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/runs")
def list_runs() -> dict[str, str]:
    """List orchestrated runs. Phase 1 wires this to memory.repo."""
    raise HTTPException(status_code=501, detail="Phase 1 — not yet wired")
