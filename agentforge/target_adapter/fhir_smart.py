"""SMART-on-FHIR adapter — master plan §4. Optional. Stub."""

from __future__ import annotations

from typing import Any

from agentforge.target_adapter.base import AdapterResponse, TargetAdapter


class FHIRSmartAdapter(TargetAdapter):
    name = "fhir_smart"

    async def execute(self, attack: Any) -> AdapterResponse:
        raise NotImplementedError("Phase 5 — not yet wired (optional)")

    def describe_action(self, attack: Any) -> str:
        return "SMART-on-FHIR OAuth flow"
