"""Internal Progress Judge — master plan §8.3.

Cheap, fast, may drift. Used by Red Team strategies (TAP/Crescendo) to prune
branches and decide whether to escalate. NEVER issues findings.
"""

from __future__ import annotations

from typing import Any


class InternalProgressJudge:
    """Layer = 'internal_progress'. Returns within ~1s. Feeds Red Team feedback only."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Phase 3 wires real dependencies (anthropic, deterministic, rubrics)."""

    async def score(self, attack: Any, response: Any) -> Any:
        """Run deterministic detectors first; only call Haiku for ambiguous cases."""
        raise NotImplementedError("Phase 3 — not yet wired")

    async def near_miss_signal(self, verdict: Any) -> dict[str, Any]:
        """Compact reframing signal for the Red Team. MUST NOT echo external rubric internals."""
        raise NotImplementedError("Phase 3 — not yet wired")
