"""/v1/runs routes — master plan §4 + Next05 §1 (live-streaming)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from agentforge.api.deps import get_session
from agentforge.api.responses import (
    RunDetail,
    RunListResponse,
    RunLiveState,
    RunRow,
    RunStartResponse,
)
from agentforge.api.run_runner import (
    get_run_state,
    start_background_run,
    stream_run_events,
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


@router.post("/runs/start", response_model=RunStartResponse)
def start_run(
    run_type: Literal["smoke", "seeded", "exploratory"] = Query(default="smoke"),
    count: int = Query(default=1, ge=1, le=10),
) -> RunStartResponse:
    """Spawn a daemon thread that runs `orchestrator.step(batch_size=count)`
    against the live sidecar. Returns immediately with a `run_id` the
    caller polls via `/v1/runs/{run_id}/state` or streams via
    `/v1/runs/{run_id}/stream`.

    Concurrency is governed by ``BUDGET_MAX_CONCURRENT_RUNS`` (default 1).
    Additional starts queue in ``status="pending"`` up to
    ``BUDGET_MAX_QUEUED_RUNS`` (default 4); beyond that the runner
    refuses with 429. Sub-plan Next05 §1 + Next06 §5.
    """
    state = start_background_run(run_type=run_type, count=count)
    if state.error and state.error.startswith("queue depth reached"):
        raise HTTPException(status_code=429, detail=state.error)
    return RunStartResponse(
        run_id=state.run_id,
        status=state.status,
        run_type=state.run_type,
        count=state.count,
    )


@router.get("/runs/{run_id}/state", response_model=RunLiveState)
def get_run_live_state(run_id: str) -> RunLiveState:
    """Return the in-memory state of a background run started via
    `POST /v1/runs/start`. 404 if the run_id was never tracked
    (e.g. server restart cleared the in-memory dict)."""
    state = get_run_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"run_id not tracked: {run_id}")
    return RunLiveState(**state.model_dump())


@router.get("/runs/{run_id}/stream")
def stream_run(run_id: str) -> StreamingResponse:
    """Server-Sent Events stream of the run's state transitions.

    Each event is a `data:`-prefixed JSON-serialized `RunLiveState`. Stream
    closes when the run reaches a terminal state (completed/failed/halted)
    AND one extra tick has been emitted so consumers receive the final
    state. Sends a `: keep-alive` comment every 15s of unchanged state to
    survive intermediate proxies. Sub-plan Next05 §1.
    """
    if get_run_state(run_id) is None:
        raise HTTPException(status_code=404, detail=f"run_id not tracked: {run_id}")
    return StreamingResponse(
        stream_run_events(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
