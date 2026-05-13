"""/v1/regression routes — master plan §4 / §13."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from agentforge.api.deps import get_session
from agentforge.api.responses import (
    RegressionCaseListResponse,
    RegressionCaseRow,
    RegressionResultRow,
    RegressionResultsResponse,
)
from agentforge.memory.models import RegressionCase

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RESULTS_DIR = _REPO_ROOT / "evals" / "results"


@router.get("/regression/cases", response_model=RegressionCaseListResponse)
def list_regression_cases(
    session: Session = Depends(get_session),
) -> RegressionCaseListResponse:
    """List regression cases."""
    rows = session.query(RegressionCase).order_by(RegressionCase.vr_id).all()
    return RegressionCaseListResponse(
        cases=[
            RegressionCaseRow(
                id=r.id,
                vr_id=r.vr_id,
                what_bug_this_catches=r.what_bug_this_catches,
                last_run_at=r.last_run_at,
                last_run_outcome=r.last_run_outcome,
            )
            for r in rows
        ]
    )


@router.get("/regression/results/latest", response_model=RegressionResultsResponse)
def latest_regression_results() -> RegressionResultsResponse:
    """Most recent regression_*.jsonl, parsed line-by-line."""
    if not _RESULTS_DIR.exists():
        return RegressionResultsResponse()
    candidates = sorted(
        _RESULTS_DIR.glob("regression_*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return RegressionResultsResponse()
    path = candidates[0]
    rows: list[RegressionResultRow] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return RegressionResultsResponse(file=str(path))
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows.append(
            RegressionResultRow(
                case_id=obj.get("case_id"),
                outcome=obj.get("outcome"),
                raw=obj,
            )
        )
    return RegressionResultsResponse(file=str(path), rows=rows)
