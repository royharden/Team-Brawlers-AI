"""Browser adapter (Playwright) — master plan §4. Gated by ALLOW_BROWSER_AUTOMATION."""

from __future__ import annotations

from typing import Any

from agentforge.target_adapter.base import AdapterResponse, TargetAdapter


class BrowserOpenEMRAdapter(TargetAdapter):
    """Playwright-driven OpenEMR adapter. Requires ALLOW_BROWSER_AUTOMATION=true."""

    name = "browser_openemr"

    async def execute(self, attack: Any) -> AdapterResponse:
        raise NotImplementedError("Phase 5 — not yet wired (requires playwright extra)")

    def describe_action(self, attack: Any) -> str:
        return "Playwright-driven OpenEMR UI flow"
