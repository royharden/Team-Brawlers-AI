"""/v1/dashboard route — aggregated UI overview (master plan §4)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from agentforge.api.deps import get_session
from agentforge.api.responses import (
    CoverageSummary,
    DashboardResponse,
    DashboardTotals,
    LatestRun,
)
from agentforge.memory.models import (
    AttackJob,
    CoverageCellRow,
    DefenseDeltaSnapshot,
    Run,
    VulnReport,
)
from agentforge.observability.dashboards import (
    aggregate_run_costs,
    coverage_pct,
)

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parents[2]
_JUDGE_META_PATH = _REPO_ROOT / "evals" / "meta_eval" / "judge_external_final_v1_metrics.json"


def _judge_floor_met() -> dict[str, bool]:
    if not _JUDGE_META_PATH.exists():
        return {}
    try:
        data = json.loads(_JUDGE_META_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    metrics = data.get("metrics") or {}
    floor_met = metrics.get("floor_met") or {}
    return {k: bool(v) for k, v in floor_met.items()}


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    session: Session = Depends(get_session),
) -> DashboardResponse:
    """Aggregated dashboard data (totals + coverage + latest run + judge floor)."""
    n_runs = session.query(Run).count()
    n_attacks = session.query(AttackJob).count()
    n_vrs_open = session.query(VulnReport).filter(VulnReport.fix_status != "fixed").count()
    n_vrs_fixed = session.query(VulnReport).filter(VulnReport.fix_status == "fixed").count()

    spend = aggregate_run_costs(session)
    total_spend: Decimal = spend["total"]

    # Coverage summary — count cells with attempts > 0.
    coverage_rows = session.query(CoverageCellRow).all()
    cells: list[dict[str, Any]] = [
        {
            "category": r.category,
            "strategy": r.strategy,
            "attempts": int(r.attempts or 0),
        }
        for r in coverage_rows
    ]
    covered = sum(1 for c in cells if int(c["attempts"]) > 0)
    pct = coverage_pct(cells)

    # Latest run.
    latest_row = session.query(Run).order_by(Run.started_at.desc(), Run.id.desc()).first()
    latest_run: LatestRun | None = None
    if latest_row is not None:
        latest_run = LatestRun(
            id=latest_row.id,
            started_at=latest_row.started_at,
            ended_at=latest_row.ended_at,
            status=latest_row.status,
            run_type=latest_row.run_type,
        )

    # Latest fingerprint snapshot.
    latest_snap = (
        session.query(DefenseDeltaSnapshot)
        .order_by(DefenseDeltaSnapshot.snapshot_at.desc(), DefenseDeltaSnapshot.id.desc())
        .first()
    )
    latest_fingerprint = latest_snap.fingerprint if latest_snap is not None else None

    return DashboardResponse(
        totals=DashboardTotals(
            runs=n_runs,
            attacks=n_attacks,
            vrs_open=n_vrs_open,
            vrs_fixed=n_vrs_fixed,
            spend_usd=str(total_spend),
        ),
        coverage_summary=CoverageSummary(
            covered_cells=covered,
            total_cells=72,
            pct=pct,
        ),
        latest_run=latest_run,
        latest_fingerprint=latest_fingerprint,
        judge_floor_met=_judge_floor_met(),
    )
