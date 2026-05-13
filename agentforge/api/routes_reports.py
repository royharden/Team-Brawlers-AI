"""/v1/reports routes — master plan §4."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/reports")
def list_reports() -> dict[str, str]:
    """List vulnerability reports. Phase 3 wires this up."""
    raise HTTPException(status_code=501, detail="Phase 3 — not yet wired")
