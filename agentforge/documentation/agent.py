"""Documentation Agent — master plan §8.4."""

from __future__ import annotations

from typing import Any


class DocumentationAgent:
    """Writes vulnerability reports. ONLY consumes external_final verdicts."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Phase 3 wires real dependencies."""

    async def write_report(
        self,
        attack: Any,
        request: Any,
        response: Any,
        verdict: Any,
        seed: Any,
    ) -> Any:
        """Render a vulnerability report.

        The first action is the binding invariant: only external_final verdicts
        may produce a VR (master plan §8.4 step 1).
        """
        assert getattr(verdict, "layer", None) == "external_final", (
            "DocumentationAgent.write_report requires layer=='external_final' "
            "(master plan §8.4)"
        )
        raise NotImplementedError("Phase 3 — not yet wired")

    async def update_after_fix(
        self, vr_id: str, regression_passes: bool, fingerprint: str
    ) -> None:
        """Update VR status when a regression case flips after a fix."""
        raise NotImplementedError("Phase 3 — not yet wired")
