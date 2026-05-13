"""/v1/reports routes — master plan §4 / §11."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from agentforge.api.deps import get_session
from agentforge.api.responses import (
    VulnReportDetail,
    VulnReportListResponse,
    VulnReportRow,
)
from agentforge.memory.models import VulnReport

router = APIRouter()


def _row_to_summary(r: VulnReport) -> VulnReportRow:
    return VulnReportRow(
        vr_id=r.vr_id,
        severity=r.severity,
        defcon=r.defcon,
        status=r.status,
        fix_status=r.fix_status,
        safety_score_0_100=r.safety_score_0_100,
        target_fingerprint_at_discovery=r.target_fingerprint_at_discovery,
        written_at=r.written_at,
    )


@router.get("/reports", response_model=VulnReportListResponse)
def list_reports(
    severity: str | None = Query(default=None),
    status: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> VulnReportListResponse:
    """List vulnerability reports. Filter by severity / status."""
    q = session.query(VulnReport)
    if severity:
        q = q.filter(VulnReport.severity == severity)
    if status:
        q = q.filter(VulnReport.status == status)
    rows = q.order_by(VulnReport.written_at.desc()).all()
    return VulnReportListResponse(reports=[_row_to_summary(r) for r in rows])


@router.get("/reports/{vr_id}.md", response_class=PlainTextResponse)
def get_report_markdown(
    vr_id: str,
    session: Session = Depends(get_session),
) -> str:
    """Raw markdown body for a single VR. Registered before the JSON variant
    so the `.md` suffix path is matched first."""
    r = session.query(VulnReport).filter_by(vr_id=vr_id).one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail=f"vuln report not found: {vr_id}")
    return r.content_markdown or ""


@router.get("/reports/{vr_id}", response_model=VulnReportDetail)
def get_report(
    vr_id: str,
    session: Session = Depends(get_session),
) -> VulnReportDetail:
    # Strip an accidental `.md` suffix so we don't shadow the markdown route
    # if FastAPI ever resolves it here first.
    if vr_id.endswith(".md"):
        raise HTTPException(status_code=404, detail=f"vuln report not found: {vr_id}")
    r = session.query(VulnReport).filter_by(vr_id=vr_id).one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail=f"vuln report not found: {vr_id}")
    summary = _row_to_summary(r)
    return VulnReportDetail(
        **summary.model_dump(),
        vulnerability_class_id=r.vulnerability_class_id,
        content_markdown=r.content_markdown or "",
    )
