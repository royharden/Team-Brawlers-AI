"""OpenEMR gateway adapter (full path through Co-Pilot UI) — master plan §4. Stub."""

from __future__ import annotations

from typing import Any

from agentforge.target_adapter.base import AdapterResponse, TargetAdapter


class OpenEMRGatewayAdapter(TargetAdapter):
    name = "openemr_gateway"

    async def execute(self, attack: Any) -> AdapterResponse:
        raise NotImplementedError("Phase 1 — not yet wired")

    def describe_action(self, attack: Any) -> str:
        return "login → CSRF → /brief.php (OpenEMR gateway)"
