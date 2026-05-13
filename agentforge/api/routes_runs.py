"""/v1/runs routes — master plan §4."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from agentforge.api.deps import get_session
from agentforge.api.responses import (
    RunDetail,
    RunListResponse,
    RunRow,
)
from agentforge.memory.models import AttackJob, AttackTrace, Run, Verdict

router = APIRouter()


def _row_to_run(r: Run) -> RunRow:
    return RunRow(
        id=r.id,
        started_at=r.started_at,
        ended_at=r.ended_at,
        run_type=r.run_type,
        status=r.status,
        total_cost_usd=str(r.total_cost_usd) if r.total_cost_usd is not None else "0",
    )


@router.get("/runs", response_model=RunListResponse)
def list_runs(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> RunListResponse:
    """Paginated list of orchestrated runs (most-recent first)."""
    total = session.query(Run).count()
    q = (
        session.query(Run)
        .order_by(Run.started_at.desc(), Run.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return RunListResponse(
        runs=[_row_to_run(r) for r in q],
        limit=limit,
        offset=offset,
        total=total,
    )


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(
    run_id: str,
    session: Session = Depends(get_session),
) -> RunDetail:
    run = session.query(Run).filter_by(id=run_id).one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    n_attacks = session.query(AttackJob).filter_by(run_id=run_id).count()
    # Verdict has no direct run_id, count via attack join.
    n_verdicts = (
        session.query(Verdict)
        .join(AttackTrace, AttackTrace.id == Verdict.attack_trace_id)
        .join(AttackJob, AttackJob.id == AttackTrace.attack_job_id)
        .filter(AttackJob.run_id == run_id)
        .count()
    )
    return RunDetail(
        run=_row_to_run(run),
        attack_count=n_attacks,
        verdict_count=n_verdicts,
    )


@router.post("/runs/start", status_code=501)
def start_run() -> dict[str, str]:
    """Kick off a new orchestrated run. Phase 8 wiring."""
    raise HTTPException(status_code=501, detail="Phase 8 wiring — mutating endpoint")
