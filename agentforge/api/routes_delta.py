"""/v1/delta routes — Defense Delta trend + per-fingerprint snapshot (master plan §4 / §12)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from agentforge.api.deps import get_session
from agentforge.api.responses import (
    DefenseDeltaSnapshotResponse,
    DefenseDeltaTrendResponse,
)
from agentforge.memory.models import DefenseDeltaSnapshot

router = APIRouter()


def _row_to_resp(r: DefenseDeltaSnapshot) -> DefenseDeltaSnapshotResponse:
    return DefenseDeltaSnapshotResponse(
        target_fingerprint=r.fingerprint,
        snapshot_at=r.snapshot_at,
        aggregate_pass_rate=r.aggregate_pass_rate or 0.0,
        by_cell=json.loads(r.by_cell_json or "{}"),
    )


@router.get("/delta/trend", response_model=DefenseDeltaTrendResponse)
def trend(
    last: int = Query(default=10, ge=1, le=200),
    session: Session = Depends(get_session),
) -> DefenseDeltaTrendResponse:
    """Most-recent ``last`` snapshots ordered by snapshot_at desc."""
    rows = (
        session.query(DefenseDeltaSnapshot)
        .order_by(
            DefenseDeltaSnapshot.snapshot_at.desc(), DefenseDeltaSnapshot.id.desc()
        )
        .limit(last)
        .all()
    )
    return DefenseDeltaTrendResponse(snapshots=[_row_to_resp(r) for r in rows])


@router.get("/delta/snapshot/{fingerprint}", response_model=DefenseDeltaSnapshotResponse)
def snapshot_for_fingerprint(
    fingerprint: str,
    session: Session = Depends(get_session),
) -> DefenseDeltaSnapshotResponse:
    """Most-recent snapshot for the given fingerprint."""
    row = (
        session.query(DefenseDeltaSnapshot)
        .filter_by(fingerprint=fingerprint)
        .order_by(
            DefenseDeltaSnapshot.snapshot_at.desc(), DefenseDeltaSnapshot.id.desc()
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"no snapshot for fingerprint: {fingerprint}"
        )
    return _row_to_resp(row)
