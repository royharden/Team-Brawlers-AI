"""/v1/regression routes — master plan §4 / §13."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/regression")
def list_regression_cases() -> dict[str, str]:
    """Regression cases. Phase 3 wires this up."""
    raise HTTPException(status_code=501, detail="Phase 3 — not yet wired")
