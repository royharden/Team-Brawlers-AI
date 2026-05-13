"""/v1/dashboard route — aggregated UI data (master plan §4)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/dashboard")
def get_dashboard() -> dict[str, str]:
    """Aggregated dashboard data. Phase 5 wires this up."""
    raise HTTPException(status_code=501, detail="Phase 5 — not yet wired")
