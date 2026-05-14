"""httpx-based thin client → FastAPI app — master plan §4.

**Architecture invariant**: this module talks to the FastAPI app over HTTP
only. It MUST NOT import ``agentforge.memory.db``, ``agentforge.memory.models``,
or ``agentforge.memory.repo``. The only ``agentforge.*`` import allowed from
the UI layer is :mod:`agentforge.api.responses` (types only, no DB code).
Enforced by ``tests/unit/ui/test_no_db_imports.py``.
"""

from __future__ import annotations

import os
from typing import Any, cast

import httpx


def _default_base_url() -> str:
    return os.environ.get("AGENTFORGE_API_URL", "http://localhost:8100")


class AgentForgeClient:
    """Synchronous httpx client that talks to the AgentForge FastAPI app."""

    def __init__(self, base_url: str | None = None, timeout: float = 10.0) -> None:
        self.base_url = base_url or _default_base_url()
        self._client: httpx.Client = httpx.Client(base_url=self.base_url, timeout=timeout)

    # --- generic ---------------------------------------------------------

    def _get_json(self, path: str, **params: Any) -> dict[str, Any]:
        resp = self._client.get(path, params=params or None)
        resp.raise_for_status()
        return cast("dict[str, Any]", resp.json())

    def _get_text(self, path: str) -> str:
        resp = self._client.get(path)
        resp.raise_for_status()
        return resp.text

    def close(self) -> None:
        self._client.close()

    # --- health ----------------------------------------------------------

    def healthz(self) -> dict[str, Any]:
        return self._get_json("/healthz")

    # --- dashboard -------------------------------------------------------

    def get_dashboard(self) -> dict[str, Any]:
        return self._get_json("/v1/dashboard")

    def get_coverage_cells(self) -> dict[str, Any]:
        return self._get_json("/v1/coverage/cells")

    # --- runs ------------------------------------------------------------

    def list_runs(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return self._get_json("/v1/runs", limit=limit, offset=offset)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._get_json(f"/v1/runs/{run_id}")

    def start_run(self, run_type: str = "smoke", count: int = 1) -> dict[str, Any]:
        resp = self._client.post(
            "/v1/runs/start",
            params={"run_type": run_type, "count": count},
        )
        resp.raise_for_status()
        return cast("dict[str, Any]", resp.json())

    def get_run_live_state(self, run_id: str) -> dict[str, Any]:
        return self._get_json(f"/v1/runs/{run_id}/state")

    # --- refusal-rate ---------------------------------------------------

    def refusal_rate(
        self,
        last: int = 100,
        *,
        since: str | None = None,
        buckets: int = 0,
        detector: str = "deterministic",
    ) -> dict[str, Any]:
        """GET /v1/refusal-rate.

        `since` (ISO 8601) and `buckets` are Next06 §2 sliding-window +
        trend extensions; `detector` is Next06 §3 (`deterministic` or
        `llm`). All three are optional and default to the pre-Next06
        behavior so the LiveRun chip keeps working unchanged.
        """
        params: dict[str, Any] = {"last": last}
        if since is not None:
            params["since"] = since
        if buckets > 0:
            params["buckets"] = buckets
        if detector != "deterministic":
            params["detector"] = detector
        return self._get_json("/v1/refusal-rate", **params)

    # --- reports ---------------------------------------------------------

    def list_reports(
        self, severity: str | None = None, status: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if severity is not None:
            params["severity"] = severity
        if status is not None:
            params["status"] = status
        return self._get_json("/v1/reports", **params)

    def get_report(self, vr_id: str) -> dict[str, Any]:
        return self._get_json(f"/v1/reports/{vr_id}")

    def get_report_markdown(self, vr_id: str) -> str:
        return self._get_text(f"/v1/reports/{vr_id}.md")

    # --- cost ------------------------------------------------------------

    def cost_today(self) -> dict[str, Any]:
        return self._get_json("/v1/cost/today")

    def cost_projections(self) -> dict[str, Any]:
        return self._get_json("/v1/cost/projections")

    # --- regression ------------------------------------------------------

    def list_regression_cases(self) -> dict[str, Any]:
        return self._get_json("/v1/regression/cases")

    def latest_regression_results(self) -> dict[str, Any]:
        return self._get_json("/v1/regression/results/latest")

    # --- lineage ---------------------------------------------------------

    def lineage(self, attack_id: str) -> dict[str, Any]:
        return self._get_json(f"/v1/lineage/{attack_id}")

    def lineage_recent(self, limit: int = 50) -> dict[str, Any]:
        return self._get_json("/v1/lineage/recent", limit=limit)

    # --- defense delta ---------------------------------------------------

    def delta_trend(self, last: int = 10) -> dict[str, Any]:
        return self._get_json("/v1/delta/trend", last=last)

    def delta_snapshot(self, fingerprint: str) -> dict[str, Any]:
        return self._get_json(f"/v1/delta/snapshot/{fingerprint}")

    # --- approval --------------------------------------------------------

    def approval_queue(self) -> dict[str, Any]:
        return self._get_json("/v1/approval/queue")

    def approve(self, vr_id: str, reviewer: str = "operator") -> dict[str, Any]:
        resp = self._client.post(f"/v1/approval/{vr_id}/approve", params={"reviewer": reviewer})
        resp.raise_for_status()
        return cast("dict[str, Any]", resp.json())

    def reject(self, vr_id: str, reviewer: str = "operator") -> dict[str, Any]:
        resp = self._client.post(f"/v1/approval/{vr_id}/reject", params={"reviewer": reviewer})
        resp.raise_for_status()
        return cast("dict[str, Any]", resp.json())

    def dismiss(self, vr_id: str, reviewer: str = "operator") -> dict[str, Any]:
        resp = self._client.post(f"/v1/approval/{vr_id}/dismiss", params={"reviewer": reviewer})
        resp.raise_for_status()
        return cast("dict[str, Any]", resp.json())

    # --- judge meta-eval -------------------------------------------------

    def recompute_judge_meta(self, layer: str = "external_final") -> dict[str, Any]:
        resp = self._client.post("/v1/judge/recompute", params={"layer": layer})
        resp.raise_for_status()
        return cast("dict[str, Any]", resp.json())


# Backwards-compat alias for the older module name.
APIClient = AgentForgeClient


__all__ = ["AgentForgeClient", "APIClient"]
