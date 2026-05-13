"""/v1/cost routes — master plan §4 / §15.

The projections endpoint computes fresh per-request from `config/pricing.yml`
+ the platform DB's `cost_ledger` (sub-plan Next03 §3.3). The on-disk
``evals/results/cost_extrapolate_*.json`` artifact is still produced by
``scripts/cost_extrapolate.py`` for the PRD-deliverable record but the
route no longer depends on it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from agentforge.api.deps import get_session
from agentforge.api.responses import (
    CostProjectionsResponse,
    CostScaleRow,
    CostTodayResponse,
)
from agentforge.cost.projections import build_projections_payload
from agentforge.observability.dashboards import aggregate_run_costs

router = APIRouter()


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
def cost_projections(
    session: Session = Depends(get_session),
) -> CostProjectionsResponse:
    """Compute the four-scale (100/1K/10K/100K) projection in-process.

    Pricing is read from ``config/pricing.yml`` and actual dev spend is
    aggregated from ``cost_ledger`` on the supplied session. No file I/O on
    the response path.
    """
    try:
        data = build_projections_payload(session)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"pricing config missing: {exc}",
        ) from exc

    scales = [
        CostScaleRow(
            n_runs=int(s.get("n_runs", 0)),
            per_run_usd=str(s.get("per_run_usd", "0")),
            total_usd=str(s.get("total_usd", "0")),
            infra_monthly_usd=str(s.get("infra_monthly_usd", "0")),
            architecture_notes=str(s.get("architecture_notes", "")),
            by_role_usd={k: str(v) for k, v in (s.get("by_role_usd") or {}).items()},
        )
        for s in data.get("scales", [])
    ]
    return CostProjectionsResponse(
        generated_at=data.get("generated_at"),
        pricing_retrieved_on=data.get("pricing_retrieved_on"),
        scales=scales,
        actual_dev_spend_usd=str(data.get("actual_dev_spend_usd", "0.00")),
    )
