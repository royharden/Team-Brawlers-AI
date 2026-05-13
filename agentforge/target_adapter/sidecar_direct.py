"""Sidecar-direct adapter — master plan §4. Stub."""

from __future__ import annotations

from typing import Any

from agentforge.target_adapter.base import AdapterResponse, TargetAdapter


class SidecarDirectAdapter(TargetAdapter):
    name = "sidecar_direct"

    async def execute(self, attack: Any) -> AdapterResponse:
        raise NotImplementedError("Phase 1 — not yet wired")

    def describe_action(self, attack: Any) -> str:
        return "POST /v1/copilot/answer (sidecar direct)"
