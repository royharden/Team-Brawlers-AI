"""External Final Judge — master plan §8.3.

This is the BINDING-VERDICT layer. Only this judge can produce a finding. Sees
only (attack, response, expected_safe_behavior, rubric). Treats text in target
response as evidence — never as instructions.
"""

from __future__ import annotations

from typing import Any


class ExternalFinalJudge:
    """Layer = 'external_final'. Independent, stable, validated against the gold set."""

    def __init__(self, *args: Any, version: str = "v1", **kwargs: Any) -> None:
        """Phase 3 wires real dependencies (anthropic, rubrics, scrubber)."""
        self.version = version

    async def verdict(self, attack: Any, response: Any, seed: Any) -> Any:
        """Runs the full rubric set for the seed's category. Returns a binding verdict."""
        raise NotImplementedError("Phase 3 — not yet wired")

    async def validate_self(self, gold_set_version: str = "v1") -> Any:
        """Run the gold set; emit precision / recall / F1 / Krippendorff alpha."""
        raise NotImplementedError("Phase 3 — not yet wired")
