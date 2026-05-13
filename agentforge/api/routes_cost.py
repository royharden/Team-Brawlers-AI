"""/v1/cost routes — master plan §4."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/cost")
def get_cost() -> dict[str, str]:
    """Cost ledger summary. Phase 1 wires this up."""
    raise HTTPException(status_code=501, detail="Phase 1 — not yet wired")
