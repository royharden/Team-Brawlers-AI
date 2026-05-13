"""/v1/lineage routes — Attack Lineage Map (master plan §4 / §8.2).

Three endpoints:

- ``GET /v1/lineage/{attack_id}`` — lineage tree for the given attack_id.
  Tries the in-process ``AttackLineage`` registry first (fast path within
  the same process); falls back to a DB-backed walk of
  ``attack_traces.parent_attack_id`` (sub-plan Next05 §2 — survives uvicorn
  restarts as long as the orchestrator wrote rows post-migration 0002).

- ``GET /v1/lineage/recent`` — DB-backed listing of the most-recent attack
  traces, joined with their AttackJob for category/strategy context. Powers
  the AttackLineage UI page's dropdown (sub-plan Next03 §3.5).

The two endpoints surface the same `attack_id` field — the agent-level
``MutatedAttack.attack_id`` (NOT the trace row's PK ``id``).
"""

from __future__ import annotations

import json
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
    freshest activity first. Limits to 50 rows by default. The
    ``attack_id`` field is the agent-level UUID (``MutatedAttack.attack_id``)
    — fall back to the trace row's PK ``id`` for pre-migration-0002 rows
    that don't yet have ``attack_id`` populated.
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
                attack_id=trace.attack_id or trace.id,
                attack_job_id=job.id,
                category=job.category,
                strategy=job.strategy,
                created_at=job.created_at,
                latency_ms=int(trace.latency_ms or 0),
                target_error=trace.target_error,
            )
        )
    return LineageRecentResponse(rows=out)


def _build_db_lineage_tree(session: Session, root_attack_id: str) -> dict[str, Any] | None:
    """Walk ``attack_traces.parent_attack_id`` to reconstruct the tree
    rooted at ``root_attack_id``. Returns None when no row matches the root
    (caller raises 404). Sub-plan Next05 §2.

    Cycle protection: a `_visited` set caps recursion depth even if a
    miswritten row points its parent at itself. The orchestrator never
    writes such rows but the migration is forward-only and could see legacy
    bad data.
    """
    root_row = (
        session.query(AttackTrace, AttackJob)
        .join(AttackJob, AttackJob.id == AttackTrace.attack_job_id)
        .filter(AttackTrace.attack_id == root_attack_id)
        .order_by(AttackJob.created_at.desc(), AttackJob.id.desc())
        .first()
    )
    if root_row is None:
        return None

    visited: set[str] = set()

    def _build(trace: AttackTrace, job: AttackJob) -> dict[str, Any]:
        if trace.attack_id in visited:
            return {
                "attack_id": trace.attack_id,
                "seed_id": job.seed_id,
                "strategy": job.strategy,
                "mutator_chain": [],
                "children": [],
                "_cycle": True,
            }
        visited.add(trace.attack_id or "")
        try:
            mutator_chain = json.loads(trace.mutator_chain_json or "[]")
            if not isinstance(mutator_chain, list):
                mutator_chain = []
        except (json.JSONDecodeError, ValueError):
            mutator_chain = []

        child_rows = (
            session.query(AttackTrace, AttackJob)
            .join(AttackJob, AttackJob.id == AttackTrace.attack_job_id)
            .filter(AttackTrace.parent_attack_id == trace.attack_id)
            .order_by(AttackJob.created_at.asc(), AttackJob.id.asc())
            .all()
        )
        return {
            "attack_id": trace.attack_id,
            "seed_id": job.seed_id,
            "strategy": job.strategy,
            "mutator_chain": [str(m) for m in mutator_chain],
            "children": [_build(child_trace, child_job) for child_trace, child_job in child_rows],
        }

    return _build(*root_row)


@router.get("/lineage/{attack_id}")
def lineage_for_attack(
    attack_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Return the lineage tree rooted at ``attack_id``.

    Resolution order:
      1. In-process ``AttackLineage`` registry (fast; same uvicorn process).
      2. DB walk of ``attack_traces.parent_attack_id`` (survives restarts;
         requires migration 0002 + post-migration writes).

    404 if neither source has the attack_id.
    """
    # Fast path — in-process registry.
    lineage = get_lineage()
    if attack_id in lineage._parents or attack_id in lineage._children:
        return lineage.tree(attack_id)
    # Slow path — DB walk.
    tree = _build_db_lineage_tree(session, attack_id)
    if tree is None:
        raise HTTPException(status_code=404, detail=f"attack_id not found: {attack_id}")
    return tree
