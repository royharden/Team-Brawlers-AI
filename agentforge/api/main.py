"""FastAPI app entry — master plan §4 / §3."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from agentforge import __version__
from agentforge.api import (
    routes_approval,
    routes_cost,
    routes_dashboard,
    routes_delta,
    routes_lineage,
    routes_regression,
    routes_reports,
    routes_runs,
)

app = FastAPI(title="AgentForge", version=__version__)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    """Liveness probe."""
    return {"status": "ok", "version": __version__, "phase": "0"}


app.include_router(routes_runs.router, prefix="/v1", tags=["runs"])
app.include_router(routes_reports.router, prefix="/v1", tags=["reports"])
app.include_router(routes_cost.router, prefix="/v1", tags=["cost"])
app.include_router(routes_regression.router, prefix="/v1", tags=["regression"])
app.include_router(routes_lineage.router, prefix="/v1", tags=["lineage"])
app.include_router(routes_delta.router, prefix="/v1", tags=["delta"])
app.include_router(routes_dashboard.router, prefix="/v1", tags=["dashboard"])
app.include_router(routes_approval.router, prefix="/v1", tags=["approval"])
