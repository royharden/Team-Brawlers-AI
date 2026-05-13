"""/v1/cost routes — master plan §4 / §15."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from agentforge.api.deps import get_session
from agentforge.api.responses import (
    CostProjectionsResponse,
    CostScaleRow,
    CostTodayResponse,
)
from agentforge.observability.dashboards import aggregate_run_costs

router = APIRouter()

# Repo root: agentforge/api/routes_cost.py -> parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
_COST_RESULTS_DIR = _REPO_ROOT / "evals" / "results"


@router.get("/cost/today", response_model=CostTodayResponse)
def cost_today(
    session: Session = Depends(get_session),
) -> CostTodayResponse:
    """Aggregate cost-ledger spend for today (UTC) by agent_role."""
    today = datetime.now(UTC).date()
    agg = aggregate_run_costs(session, since_date=today)
    return CostTodayResponse(
        spend_usd=str(agg["total"]),
        n_calls=agg["n_calls"],
        by_role={role: str(amt) for role, amt in agg["by_role"].items()},
    )


@router.get("/cost/projections", response_model=CostProjectionsResponse)
def cost_projections() -> CostProjectionsResponse:
    """Return the latest cost-extrapolate output."""
    if not _COST_RESULTS_DIR.exists():
        return CostProjectionsResponse()
    candidates = sorted(
        _COST_RESULTS_DIR.glob("cost_extrapolate_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return CostProjectionsResponse()
    try:
        data = json.loads(candidates[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"unreadable cost projections file: {exc}",
        ) from exc

    scales = []
    for s in data.get("scales", []):
        scales.append(
            CostScaleRow(
                n_runs=int(s.get("n_runs", 0)),
                per_run_usd=str(s.get("per_run_usd", "0")),
                total_usd=str(s.get("total_usd", "0")),
                infra_monthly_usd=str(s.get("infra_monthly_usd", "0")),
                architecture_notes=str(s.get("architecture_notes", "")),
                by_role_usd={k: str(v) for k, v in (s.get("by_role_usd") or {}).items()},
            )
        )
    return CostProjectionsResponse(
        generated_at=data.get("generated_at"),
        pricing_retrieved_on=data.get("pricing_retrieved_on"),
        scales=scales,
        actual_dev_spend_usd=str(data.get("actual_dev_spend_usd", "0.00")),
    )
