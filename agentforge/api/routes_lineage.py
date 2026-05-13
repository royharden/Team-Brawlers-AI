"""/v1/lineage routes — Attack Lineage Map (master plan §4 / §8.2).

Two endpoints:

- ``GET /v1/lineage/{attack_id}`` — in-process AttackLineage tree (registered
  by the orchestrator at runtime; 404 across uvicorn restarts because the
  registry is in memory only).

- ``GET /v1/lineage/recent`` — DB-backed listing of the most-recent attack
  traces, joined with their AttackJob for category/strategy context. Powers
  the AttackLineage UI page's dropdown so the operator can pick a real
  attack_id without typing a UUID. (Sub-plan Next03 §3.5.)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from agentforge.api.deps import get_session
from agentforge.api.responses import LineageRecentResponse, LineageRecentRow
from agentforge.memory.models import AttackJob, AttackTrace
from agentforge.redteam.lineage import AttackLineage

router = APIRouter()


_lineage_registry: AttackLineage = AttackLineage()


def set_lineage(lineage: AttackLineage) -> None:
    """Inject the active lineage tracker — used by the orchestrator + tests."""
    global _lineage_registry
    _lineage_registry = lineage


def get_lineage() -> AttackLineage:
    return _lineage_registry


@router.get("/lineage/recent", response_model=LineageRecentResponse)
def lineage_recent(
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_session),
) -> LineageRecentResponse:
    """Most-recent attack traces joined with their AttackJob context.

    Ordered by ``attack_jobs.created_at DESC`` so the operator sees the
    freshest activity first. Limits to 50 rows by default.
    """
    rows = (
        session.query(AttackTrace, AttackJob)
        .join(AttackJob, AttackJob.id == AttackTrace.attack_job_id)
        .order_by(AttackJob.created_at.desc(), AttackJob.id.desc())
        .limit(limit)
        .all()
    )
    out: list[LineageRecentRow] = []
    for trace, job in rows:
        out.append(
            LineageRecentRow(
                attack_id=trace.id,
                attack_job_id=job.id,
                category=job.category,
                strategy=job.strategy,
                created_at=job.created_at,
                latency_ms=int(trace.latency_ms or 0),
                target_error=trace.target_error,
            )
        )
    return LineageRecentResponse(rows=out)


@router.get("/lineage/{attack_id}")
def lineage_for_attack(attack_id: str) -> dict[str, Any]:
    """Return the lineage tree rooted at ``attack_id``.

    Reads the in-process AttackLineage registry — empty across uvicorn
    restarts. Use ``/v1/lineage/recent`` to discover ``attack_id`` values
    persisted in ``attack_traces``.
    """
    lineage = get_lineage()
    # AttackLineage has no "exists" predicate; check the children map directly.
    known = attack_id in lineage._parents or attack_id in lineage._children
    if not known:
        raise HTTPException(status_code=404, detail=f"attack_id not found: {attack_id}")
    return lineage.tree(attack_id)
