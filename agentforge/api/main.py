"""FastAPI app entry — master plan §4 / §3.

Routers under ``/v1/``. CORS is restricted to localhost / 127.0.0.1 origins
(no wildcard) per AgDR-0002's local-only posture — the dashboard runs on the
operator's machine, never as a public service.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

# Phase 5: 337 tests passing on `main` at handoff. Updated as the suite grows.
TESTS_PASSING_AT_BUILD: int = 337


def _build_app() -> FastAPI:
    app = FastAPI(title="AgentForge", version=__version__)

    # Localhost-only CORS — regex matches http(s)://localhost:* and 127.0.0.1:*.
    # No wildcard origins; aligns with AgDR-0002's "local-only" stance.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$").pattern,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        """Liveness probe with version + phase + suite size at build time."""
        return {
            "status": "ok",
            "version": __version__,
            "phase": "5",
            "tests_passing": TESTS_PASSING_AT_BUILD,
        }

    app.include_router(routes_runs.router, prefix="/v1", tags=["runs"])
    app.include_router(routes_reports.router, prefix="/v1", tags=["reports"])
    app.include_router(routes_cost.router, prefix="/v1", tags=["cost"])
    app.include_router(routes_regression.router, prefix="/v1", tags=["regression"])
    app.include_router(routes_lineage.router, prefix="/v1", tags=["lineage"])
    app.include_router(routes_delta.router, prefix="/v1", tags=["delta"])
    app.include_router(routes_dashboard.router, prefix="/v1", tags=["dashboard"])
    app.include_router(routes_approval.router, prefix="/v1", tags=["approval"])

    return app


app = _build_app()


__all__ = ["app", "TESTS_PASSING_AT_BUILD"]
