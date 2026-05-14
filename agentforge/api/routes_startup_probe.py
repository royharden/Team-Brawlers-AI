"""/v1/startup-probe — Next06 §1, defensive AgDR-0027 follow-on.

Pings every model the orchestrator factory would wire (Anthropic
Sonnet + Haiku, OpenRouter Red Team primary + fallback, OpenAI direct
fallback per AgDR-0024) and returns one row per (provider, role, model)
with reachability status.

Intentionally on-demand rather than wired into FastAPI's startup hook:
burning provider tokens on every uvicorn reload is the wrong dev-loop
trade-off. Operators curl this after deploys or surface it in the UI
for a permanent "is every model reachable?" panel.
"""

from __future__ import annotations

from fastapi import APIRouter

from agentforge.api.responses import StartupProbeResponse, StartupProbeRow
from agentforge.llm.startup_probe import ProbeResult, probe_all_configured_models

router = APIRouter()


def _to_row(result: ProbeResult) -> StartupProbeRow:
    return StartupProbeRow(
        provider=result.provider,
        role=result.role,
        model=result.model,
        status=result.status,
        error=result.error,
        latency_ms=result.latency_ms,
    )


@router.get("/startup-probe", response_model=StartupProbeResponse)
def get_startup_probe() -> StartupProbeResponse:
    """Run a fresh probe against every configured model. Burns provider
    tokens (a few per model) — do not poll this endpoint."""
    results = probe_all_configured_models()
    rows = [_to_row(r) for r in results]
    n_ok = sum(1 for r in results if r.status == "ok")
    n_error = sum(1 for r in results if r.status == "error")
    n_missing_key = sum(1 for r in results if r.status == "missing_key")
    return StartupProbeResponse(
        rows=rows,
        n_ok=n_ok,
        n_error=n_error,
        n_missing_key=n_missing_key,
    )
