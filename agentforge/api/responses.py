"""Pydantic response models for the FastAPI surface — master plan §4 / §11.

Shared by the FastAPI route layer and the Streamlit UI client so OpenAPI docs
and typed UI calls stay in sync. The UI is allowed to import from this module
(types only); it must NOT import from `agentforge.memory.*` (HTTP-only
boundary — AgDR-0002 local-only stance, enforced by
`tests/unit/ui/test_no_db_imports.py`).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# --- Health -------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    version: str
    phase: str
    tests_passing: int


# --- Dashboard ----------------------------------------------------------------


class DashboardTotals(BaseModel):
    runs: int = 0
    attacks: int = 0
    vrs_open: int = 0
    vrs_fixed: int = 0
    spend_usd: str = "0.00"


class CoverageSummary(BaseModel):
    covered_cells: int = 0
    total_cells: int = 72
    pct: float = 0.0


class LatestRun(BaseModel):
    id: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: str = "running"
    run_type: str = "exploratory"


class DashboardResponse(BaseModel):
    totals: DashboardTotals = Field(default_factory=DashboardTotals)
    coverage_summary: CoverageSummary = Field(default_factory=CoverageSummary)
    latest_run: LatestRun | None = None
    latest_fingerprint: str | None = None
    judge_floor_met: dict[str, bool] = Field(default_factory=dict)


# --- Runs ---------------------------------------------------------------------


class RunRow(BaseModel):
    id: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    run_type: str
    status: str
    total_cost_usd: str = "0.000000"


class RunListResponse(BaseModel):
    runs: list[RunRow] = Field(default_factory=list)
    limit: int = 50
    offset: int = 0
    total: int = 0


class RunDetail(BaseModel):
    run: RunRow
    attack_count: int = 0
    verdict_count: int = 0


# --- VR reports ---------------------------------------------------------------


class VulnReportRow(BaseModel):
    vr_id: str
    severity: str
    defcon: int
    status: str
    fix_status: str
    safety_score_0_100: int
    target_fingerprint_at_discovery: str
    written_at: datetime | None = None


class VulnReportListResponse(BaseModel):
    reports: list[VulnReportRow] = Field(default_factory=list)


class VulnReportDetail(VulnReportRow):
    vulnerability_class_id: str
    content_markdown: str = ""


# --- Cost ---------------------------------------------------------------------


class CostTodayResponse(BaseModel):
    spend_usd: str = "0.000000"
    n_calls: int = 0
    by_role: dict[str, str] = Field(default_factory=dict)


class CostScaleRow(BaseModel):
    n_runs: int
    per_run_usd: str
    total_usd: str
    infra_monthly_usd: str
    architecture_notes: str = ""
    by_role_usd: dict[str, str] = Field(default_factory=dict)


class CostProjectionsResponse(BaseModel):
    generated_at: str | None = None
    pricing_retrieved_on: str | None = None
    scales: list[CostScaleRow] = Field(default_factory=list)
    actual_dev_spend_usd: str = "0.00"


# --- Regression ---------------------------------------------------------------


class RegressionCaseRow(BaseModel):
    id: str
    vr_id: str
    what_bug_this_catches: str
    last_run_at: datetime | None = None
    last_run_outcome: str | None = None


class RegressionCaseListResponse(BaseModel):
    cases: list[RegressionCaseRow] = Field(default_factory=list)


class RegressionResultRow(BaseModel):
    case_id: str | None = None
    outcome: str | None = None
    raw: dict = Field(default_factory=dict)


class RegressionResultsResponse(BaseModel):
    file: str | None = None
    rows: list[RegressionResultRow] = Field(default_factory=list)


# --- Lineage ------------------------------------------------------------------


class LineageNode(BaseModel):
    attack_id: str
    seed_id: str | None = None
    strategy: str | None = None
    mutator_chain: list[str] = Field(default_factory=list)
    children: list[LineageNode] = Field(default_factory=list)


LineageNode.model_rebuild()


# --- Defense delta ------------------------------------------------------------


class DefenseDeltaSnapshotResponse(BaseModel):
    target_fingerprint: str
    snapshot_at: datetime
    aggregate_pass_rate: float
    by_cell: dict[str, float] = Field(default_factory=dict)


class DefenseDeltaTrendResponse(BaseModel):
    snapshots: list[DefenseDeltaSnapshotResponse] = Field(default_factory=list)


# --- Approval queue -----------------------------------------------------------


class ApprovalQueueItem(BaseModel):
    vr_id: str | None = None
    kind: str | None = None
    payload: dict = Field(default_factory=dict)


class ApprovalQueueResponse(BaseModel):
    items: list[ApprovalQueueItem] = Field(default_factory=list)


__all__ = [
    "HealthResponse",
    "DashboardResponse",
    "DashboardTotals",
    "CoverageSummary",
    "LatestRun",
    "RunRow",
    "RunListResponse",
    "RunDetail",
    "VulnReportRow",
    "VulnReportListResponse",
    "VulnReportDetail",
    "CostTodayResponse",
    "CostScaleRow",
    "CostProjectionsResponse",
    "RegressionCaseRow",
    "RegressionCaseListResponse",
    "RegressionResultRow",
    "RegressionResultsResponse",
    "LineageNode",
    "DefenseDeltaSnapshotResponse",
    "DefenseDeltaTrendResponse",
    "ApprovalQueueItem",
    "ApprovalQueueResponse",
]
